"""
Core memory read/write engine for Linux using /proc/PID/mem and /proc/PID/maps.

Requires either:
  - Running as root, OR
  - The target process being a child of this process (ptrace_scope=1), OR
  - ptrace_scope set to 0 in /proc/sys/kernel/yama/ptrace_scope

Speed optimisations (same as Windows version):
  - numpy vectorised search replaces the Python inner loop (~20-50x faster)
  - bytes.find() fast-path for exact-value first scans
  - Next scan re-reads whole memory regions in one read call and filters in numpy
  - Thread pool parallelises first-scan across CPU cores
"""

import os
import struct
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np

from stealth import (
    StealthConfig, open_process_stealth, clear_debug_flags,
    nt_read, nt_write, stealth_delay, set_thread_name,
)

VALUE_TYPES = {
    "Int8":   ("<b", 1),
    "UInt8":  ("<B", 1),
    "Int16":  ("<h", 2),
    "UInt16": ("<H", 2),
    "Int32":  ("<i", 4),
    "UInt32": ("<I", 4),
    "Int64":  ("<q", 8),
    "UInt64": ("<Q", 8),
    "Float":  ("<f", 4),
    "Double": ("<d", 8),
}

_NP_DTYPE = {
    "Int8":   np.dtype("<i1"),
    "UInt8":  np.dtype("<u1"),
    "Int16":  np.dtype("<i2"),
    "UInt16": np.dtype("<u2"),
    "Int32":  np.dtype("<i4"),
    "UInt32": np.dtype("<u4"),
    "Int64":  np.dtype("<i8"),
    "UInt64": np.dtype("<u8"),
    "Float":  np.dtype("<f4"),
    "Double": np.dtype("<f8"),
}

SCAN_EXACT      = "exact"
SCAN_GREATER    = "greater"
SCAN_LESS       = "less"
SCAN_BETWEEN    = "between"
SCAN_NOT_EQUAL  = "not_equal"
SCAN_CHANGED    = "changed"
SCAN_UNCHANGED  = "unchanged"
SCAN_INCREASED  = "increased"
SCAN_DECREASED  = "decreased"
SCAN_INC_BY     = "increased_by"
SCAN_DEC_BY     = "decreased_by"
SCAN_UNKNOWN    = "unknown_initial"

SCAN_LABELS = {
    SCAN_EXACT:     "Exact Value",
    SCAN_NOT_EQUAL: "Not Equal",
    SCAN_GREATER:   "Greater Than",
    SCAN_LESS:      "Less Than",
    SCAN_BETWEEN:   "Between",
    SCAN_CHANGED:   "Changed",
    SCAN_UNCHANGED: "Unchanged",
    SCAN_INCREASED: "Increased",
    SCAN_DECREASED: "Decreased",
    SCAN_INC_BY:    "Increased By",
    SCAN_DEC_BY:    "Decreased By",
    SCAN_UNKNOWN:   "Unknown Initial",
}

FIRST_SCAN_MODES = [SCAN_EXACT, SCAN_NOT_EQUAL, SCAN_GREATER, SCAN_LESS,
                    SCAN_BETWEEN, SCAN_UNKNOWN]
NEXT_SCAN_MODES  = [SCAN_EXACT, SCAN_NOT_EQUAL, SCAN_GREATER, SCAN_LESS,
                    SCAN_BETWEEN, SCAN_CHANGED, SCAN_UNCHANGED,
                    SCAN_INCREASED, SCAN_DECREASED, SCAN_INC_BY, SCAN_DEC_BY]

NEEDS_VALUE1 = {SCAN_EXACT, SCAN_NOT_EQUAL, SCAN_GREATER, SCAN_LESS,
                SCAN_BETWEEN, SCAN_INC_BY, SCAN_DEC_BY}
NEEDS_VALUE2 = {SCAN_BETWEEN}


@dataclass
class ProcessInfo:
    pid: int
    name: str


@dataclass
class ScanResult:
    address: int
    value: object
    prev_value: object


@dataclass
class ScanStats:
    duration: float = 0.0
    bytes_scanned: int = 0
    regions: int = 0

    @property
    def mb_per_sec(self) -> float:
        if self.duration <= 0:
            return 0.0
        return (self.bytes_scanned / 1_048_576) / self.duration


# ── Process list ───────────────────────────────────────────────────────────

def list_processes() -> list[ProcessInfo]:
    results = []
    try:
        for entry in os.scandir("/proc"):
            if not entry.is_dir() or not entry.name.isdigit():
                continue
            pid = int(entry.name)
            try:
                with open(f"/proc/{pid}/comm") as f:
                    name = f.read().strip()
            except OSError:
                name = f"pid{pid}"
            results.append(ProcessInfo(pid=pid, name=name))
    except OSError:
        pass
    return sorted(results, key=lambda p: p.name.lower())


# ── numpy scan helpers (identical to Windows version) ─────────────────────

def _np_mask_first(arr: np.ndarray, mode: str, v1, v2) -> np.ndarray:
    if mode == SCAN_EXACT:
        return arr == v1
    if mode == SCAN_NOT_EQUAL:
        return arr != v1
    if mode == SCAN_GREATER:
        return arr > v1
    if mode == SCAN_LESS:
        return arr < v1
    if mode == SCAN_BETWEEN:
        lo, hi = (v1, v2) if v1 <= v2 else (v2, v1)
        return (arr >= lo) & (arr <= hi)
    if mode == SCAN_UNKNOWN:
        return np.ones(len(arr), dtype=bool)
    return np.ones(len(arr), dtype=bool)


def _np_mask_next(cur: np.ndarray, prev: np.ndarray,
                  mode: str, v1, v2) -> np.ndarray:
    if mode == SCAN_EXACT:
        return cur == v1
    if mode == SCAN_NOT_EQUAL:
        return cur != v1
    if mode == SCAN_GREATER:
        return cur > v1
    if mode == SCAN_LESS:
        return cur < v1
    if mode == SCAN_BETWEEN:
        lo, hi = (v1, v2) if v1 <= v2 else (v2, v1)
        return (cur >= lo) & (cur <= hi)
    if mode == SCAN_CHANGED:
        return cur != prev
    if mode == SCAN_UNCHANGED:
        return cur == prev
    if mode == SCAN_INCREASED:
        return cur > prev
    if mode == SCAN_DECREASED:
        return cur < prev
    if mode == SCAN_INC_BY:
        return (cur - prev) == v1
    if mode == SCAN_DEC_BY:
        return (prev - cur) == v1
    return np.ones(len(cur), dtype=bool)


def _scan_region_numpy(buf: bytes, base: int, dtype: np.dtype,
                       item_size: int, alignment: int,
                       mode: str, v1, v2) -> list[ScanResult]:
    raw = np.frombuffer(buf, dtype=np.uint8)
    n = len(raw)
    limit = n - item_size + 1

    offsets = np.arange(0, limit, alignment, dtype=np.int64)
    if len(offsets) == 0:
        return []

    if mode == SCAN_EXACT and alignment == item_size:
        n_elems = (n - (n % item_size)) // item_size
        arr = np.frombuffer(buf[:n_elems * item_size], dtype=dtype)
        mask = _np_mask_first(arr, mode, v1, v2)
        hit_indices = np.where(mask)[0]
        results = []
        for idx in hit_indices:
            off = int(idx) * item_size
            val = arr[idx].item()
            results.append(ScanResult(address=base + off, value=val, prev_value=val))
        return results

    if mode == SCAN_EXACT and alignment == 1:
        target = dtype.type(v1).tobytes() if not isinstance(v1, float) else \
                 np.array([v1], dtype=dtype).tobytes()
        results = []
        pos = 0
        while True:
            pos = buf.find(target, pos)
            if pos == -1 or pos + item_size > n:
                break
            val = np.frombuffer(buf[pos:pos+item_size], dtype=dtype)[0].item()
            results.append(ScanResult(address=base + pos, value=val, prev_value=val))
            pos += 1
        return results

    shape   = (len(offsets), item_size)
    strides = (alignment, 1)
    try:
        strided = np.lib.stride_tricks.as_strided(raw, shape=shape,
                                                   strides=strides,
                                                   writeable=False)
        arr = np.frombuffer(strided.tobytes(), dtype=dtype)
    except Exception:
        return []

    mask = _np_mask_first(arr, mode, v1, v2)
    hit_offsets = offsets[mask]
    hit_values  = arr[mask]
    results = []
    for off, val in zip(hit_offsets.tolist(), hit_values.tolist()):
        results.append(ScanResult(address=base + off, value=val, prev_value=val))
    return results


# ── Linux /proc memory I/O ────────────────────────────────────────────────

def _parse_maps(pid: int) -> list[tuple[int, int, str]]:
    """
    Parse /proc/PID/maps and return readable, non-special regions.
    Each entry is (start, size, perms).
    We skip regions with no read permission and special pseudo-files
    (vdso, vsyscall, stack guard pages) that will always fail.
    """
    regions = []
    try:
        with open(f"/proc/{pid}/maps") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 5:
                    continue
                addrs, perms = parts[0], parts[1]
                # Skip non-readable regions
                if 'r' not in perms:
                    continue
                # Skip vsyscall — it cannot be read via /proc/mem
                pathname = parts[5] if len(parts) > 5 else ""
                if "[vsyscall]" in pathname:
                    continue
                start_s, end_s = addrs.split("-")
                start = int(start_s, 16)
                end   = int(end_s, 16)
                size  = end - start
                if size > 0:
                    regions.append((start, size, perms))
    except OSError:
        pass
    return regions


def _read_proc_mem(pid: int, address: int, size: int) -> bytes | None:
    try:
        with open(f"/proc/{pid}/mem", "rb") as f:
            f.seek(address)
            data = f.read(size)
            if len(data) == size:
                return data
    except OSError:
        pass
    return None


def _write_proc_mem(pid: int, address: int, data: bytes) -> bool:
    try:
        with open(f"/proc/{pid}/mem", "r+b") as f:
            f.seek(address)
            f.write(data)
            return True
    except OSError:
        return False


# ── Engine ────────────────────────────────────────────────────────────────

class MemoryEngine:
    def __init__(self):
        self.handle: int | None = None   # on Linux: the PID
        self.pid:    int | None = None
        self._results: list[ScanResult] = []
        self._has_scanned  = False
        self._scan_count   = 0
        self._cancelled    = False
        self.last_stats    = ScanStats()
        self.stealth       = StealthConfig()

    # ── Attach / Detach ────────────────────────────────────────────────────

    def attach(self, pid: int) -> bool:
        self.detach()
        handle = open_process_stealth(pid, self.stealth)
        if handle is None:
            return False
        # Verify we can actually open /proc/PID/mem for reading
        try:
            with open(f"/proc/{pid}/mem", "rb"):
                pass
        except OSError:
            return False
        self.handle = handle
        self.pid = pid
        self._reset()
        return True

    def detach(self):
        self.handle = None
        self.pid    = None
        self._reset()

    def _reset(self):
        self._results     = []
        self._has_scanned = False
        self._scan_count  = 0
        self._cancelled   = False

    def cancel(self):
        self._cancelled = True

    # ── Region iteration ───────────────────────────────────────────────────

    def _iter_readable_regions(self) -> Iterator[tuple[int, int]]:
        if not self.pid:
            return
        for start, size, _perms in _parse_maps(self.pid):
            yield start, size

    # ── Raw I/O ────────────────────────────────────────────────────────────

    def _read_raw(self, address: int, size: int) -> bytes | None:
        if not self.pid:
            return None
        return _read_proc_mem(self.pid, address, size)

    def read_value(self, address: int, vtype: str) -> object | None:
        fmt, size = VALUE_TYPES[vtype]
        raw = self._read_raw(address, size)
        if raw:
            return struct.unpack(fmt, raw)[0]
        return None

    def write_value(self, address: int, value: object, vtype: str) -> bool:
        if not self.pid:
            return False
        fmt, size = VALUE_TYPES[vtype]
        try:
            raw = struct.pack(fmt, value)
        except (struct.error, OverflowError):
            return False
        return _write_proc_mem(self.pid, address, raw)

    # ── First scan (numpy + thread pool) ─────────────────────────────────

    def first_scan(self, mode: str, vtype: str,
                   value1=None, value2=None,
                   alignment: int = 4,
                   progress_cb: Callable | None = None) -> list[ScanResult]:
        fmt, item_size = VALUE_TYPES[vtype]
        dtype = _NP_DTYPE[vtype]
        alignment = max(1, alignment)
        self._cancelled = False

        regions    = list(self._iter_readable_regions())
        total_bytes = sum(s for _, s in regions)
        t0 = time.perf_counter()

        done_bytes = [0]
        pid = self.pid
        stealth_cfg = self.stealth

        def process_region(args) -> list[ScanResult]:
            base, size = args
            if self._cancelled:
                return []
            set_thread_name("SystemWorker")
            stealth_delay(stealth_cfg)
            buf = _read_proc_mem(pid, base, size)
            done_bytes[0] += size
            if progress_cb:
                progress_cb(done_bytes[0], total_bytes)
            if not buf:
                return []
            return _scan_region_numpy(buf, base, dtype, item_size,
                                      alignment, mode, value1, value2)

        all_results: list[ScanResult] = []
        cpu_count = max(1, os.cpu_count() or 4)
        workers = min(cpu_count, 8)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(process_region, r) for r in regions]
            for f in as_completed(futures):
                chunk = f.result()
                if chunk:
                    all_results.extend(chunk)

        all_results.sort(key=lambda r: r.address)

        elapsed = time.perf_counter() - t0
        self.last_stats   = ScanStats(elapsed, total_bytes, len(regions))
        self._results     = all_results
        self._has_scanned = True
        self._scan_count  = 1
        return all_results

    # ── Next scan ────────────────────────────────────────────────────────

    def next_scan(self, mode: str, vtype: str,
                  value1=None, value2=None,
                  progress_cb: Callable | None = None) -> list[ScanResult]:
        if not self._has_scanned:
            return self.first_scan(mode, vtype, value1, value2,
                                   progress_cb=progress_cb)

        fmt, item_size = VALUE_TYPES[vtype]
        dtype = _NP_DTYPE[vtype]
        self._cancelled = False
        t0 = time.perf_counter()

        regions = list(self._iter_readable_regions())
        region_map: dict[tuple[int, int], list[ScanResult]] = {}
        for r in self._results:
            for base, size in regions:
                if base <= r.address < base + size:
                    key = (base, size)
                    region_map.setdefault(key, []).append(r)
                    break

        surviving: list[ScanResult] = []
        total = len(regions)

        for i, (base, size) in enumerate(regions):
            if self._cancelled:
                break
            if progress_cb:
                progress_cb(i, total)

            bucket = region_map.get((base, size))
            if not bucket:
                continue

            buf = self._read_raw(base, size)
            if buf is None:
                continue

            offsets_list = [r.address - base for r in bucket]
            prev_list    = [r.prev_value if r.prev_value is not None
                            else r.value for r in bucket]

            cur_vals  = np.empty(len(offsets_list), dtype=dtype)
            prev_vals = np.array(prev_list, dtype=dtype)

            valid = np.ones(len(offsets_list), dtype=bool)
            for j, off in enumerate(offsets_list):
                end = off + item_size
                if end > len(buf):
                    valid[j] = False
                    continue
                cur_vals[j] = np.frombuffer(buf[off:end], dtype=dtype)[0]

            cur_vals  = cur_vals[valid]
            prev_vals = prev_vals[valid]
            valid_bucket = [r for r, v in zip(bucket, valid) if v]

            if len(cur_vals) == 0:
                continue

            mask = _np_mask_next(cur_vals, prev_vals, mode, value1, value2)
            for r, cur, keep in zip(valid_bucket, cur_vals.tolist(), mask.tolist()):
                if keep:
                    r.prev_value = r.value
                    r.value = cur
                    surviving.append(r)

        elapsed = time.perf_counter() - t0
        self.last_stats  = ScanStats(elapsed, 0, 0)
        self._results    = surviving
        self._scan_count += 1
        return surviving

    # ── Reset ─────────────────────────────────────────────────────────────

    def reset_scan(self):
        self._results     = []
        self._has_scanned = False
        self._scan_count  = 0
        self._cancelled   = False

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def results(self) -> list[ScanResult]:
        return self._results

    @property
    def has_scanned(self) -> bool:
        return self._has_scanned

    @property
    def scan_count(self) -> int:
        return self._scan_count
