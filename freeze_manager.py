"""
Safe Freeze Manager — periodically re-writes frozen values with crash protection.

Safety features:
  - Safe mode: only write when current value differs from freeze target
    (avoids hammering memory that the app is actively using)
  - Write-verify: after writing, read back and confirm — auto-disable on mismatch
  - Per-address error counting: auto-unfreeze after N consecutive failures
  - Adjustable interval: 50ms (aggressive) to 2000ms (gentle)
  - Emergency kill-switch: unfreeze_all() callable from any thread instantly
  - Callbacks: notify UI when an address is auto-disabled due to errors
"""

import threading
import time
import struct
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class FreezeEntry:
    value: object
    vtype: str
    safe_mode: bool = True       # only write when value drifted
    verify: bool = True          # read-back verify after write
    error_count: int = 0
    max_errors: int = 3          # auto-disable after this many consecutive failures
    disabled: bool = False       # set True when auto-disabled due to errors
    write_count: int = 0         # total successful writes
    last_error: str = ""


class FreezeManager:
    def __init__(self, engine,
                 interval: float = 0.25,
                 on_auto_disable: Callable[[int, str], None] | None = None):
        """
        engine        — MemoryEngine instance
        interval      — seconds between freeze write cycles (default 250ms)
        on_auto_disable — callback(address, reason) when an entry is auto-disabled
        """
        self._engine       = engine
        self._interval     = interval
        self._entries: dict[int, FreezeEntry] = {}
        self._lock         = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running      = False
        self._on_auto_disable = on_auto_disable

        # Emergency kill event — set() instantly pauses all writes
        self._emergency = threading.Event()

    # ── Public API ─────────────────────────────────────────────────────────

    def freeze(self, address: int, value: object, vtype: str,
               safe_mode: bool = True, verify: bool = True):
        with self._lock:
            self._entries[address] = FreezeEntry(
                value=value, vtype=vtype,
                safe_mode=safe_mode, verify=verify)
        self._ensure_running()

    def unfreeze(self, address: int):
        with self._lock:
            self._entries.pop(address, None)

    def unfreeze_all(self):
        """Emergency kill — clears everything instantly (thread-safe)."""
        with self._lock:
            self._entries.clear()

    def emergency_pause(self):
        """Stop all writes immediately without removing entries."""
        self._emergency.set()

    def emergency_resume(self):
        """Resume writes after an emergency pause."""
        self._emergency.clear()

    def is_frozen(self, address: int) -> bool:
        with self._lock:
            e = self._entries.get(address)
            return e is not None and not e.disabled

    def is_disabled(self, address: int) -> bool:
        with self._lock:
            e = self._entries.get(address)
            return e is not None and e.disabled

    def update_freeze_value(self, address: int, value: object, vtype: str):
        with self._lock:
            if address in self._entries:
                e = self._entries[address]
                e.value = value
                e.vtype = vtype
                e.error_count = 0
                e.disabled = False

    def set_interval(self, seconds: float):
        self._interval = max(0.05, min(seconds, 5.0))

    def set_safe_mode(self, address: int, enabled: bool):
        with self._lock:
            if address in self._entries:
                self._entries[address].safe_mode = enabled

    def set_verify(self, address: int, enabled: bool):
        with self._lock:
            if address in self._entries:
                self._entries[address].verify = enabled

    def reenable(self, address: int):
        """Re-enable an auto-disabled entry after the user acknowledges."""
        with self._lock:
            if address in self._entries:
                e = self._entries[address]
                e.disabled = False
                e.error_count = 0
                e.last_error = ""
        self._ensure_running()

    def get_entry(self, address: int) -> FreezeEntry | None:
        with self._lock:
            e = self._entries.get(address)
            if e is None:
                return None
            # Return a shallow copy so caller doesn't hold the lock
            import copy
            return copy.copy(e)

    def get_all_entries(self) -> dict[int, FreezeEntry]:
        with self._lock:
            import copy
            return {addr: copy.copy(e) for addr, e in self._entries.items()}

    @property
    def interval(self) -> float:
        return self._interval

    def stop(self):
        self._running = False

    # ── Internal loop ──────────────────────────────────────────────────────

    def _ensure_running(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="MemEd-FreezeWorker")
        self._thread.start()

    def _loop(self):
        while self._running:
            # Emergency pause: wait until resumed
            if self._emergency.is_set():
                time.sleep(0.05)
                continue

            with self._lock:
                items = list(self._entries.items())

            if not items:
                self._running = False
                break

            for addr, entry in items:
                if self._emergency.is_set():
                    break
                if entry.disabled:
                    continue
                self._process_entry(addr, entry)

            time.sleep(self._interval)

    def _process_entry(self, addr: int, entry: FreezeEntry):
        engine = self._engine
        if not engine.handle:
            return

        try:
            fmt, size = _get_fmt_size(entry.vtype)

            # Safe mode: read current value first, skip write if already correct
            if entry.safe_mode:
                current = engine.read_value(addr, entry.vtype)
                if current is None:
                    self._record_error(addr, entry, "read failed (safe-mode check)")
                    return
                if current == entry.value:
                    # Value is already what we want — no write needed
                    entry.error_count = 0
                    return

            # Write
            ok = engine.write_value(addr, entry.value, entry.vtype)
            if not ok:
                self._record_error(addr, entry, "write failed")
                return

            # Verify
            if entry.verify:
                readback = engine.read_value(addr, entry.vtype)
                if readback is None:
                    self._record_error(addr, entry, "verify read failed")
                    return
                if not _values_equal(readback, entry.value, entry.vtype):
                    self._record_error(addr, entry,
                                       f"verify mismatch: wrote {entry.value}, "
                                       f"read back {readback}")
                    return

            # Success
            with self._lock:
                if addr in self._entries:
                    self._entries[addr].error_count = 0
                    self._entries[addr].write_count += 1

        except Exception as ex:
            self._record_error(addr, entry, str(ex))

    def _record_error(self, addr: int, entry: FreezeEntry, reason: str):
        with self._lock:
            if addr not in self._entries:
                return
            e = self._entries[addr]
            e.error_count += 1
            e.last_error = reason
            if e.error_count >= e.max_errors:
                e.disabled = True

        if entry.error_count >= entry.max_errors:
            if self._on_auto_disable:
                try:
                    self._on_auto_disable(addr, reason)
                except Exception:
                    pass


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_fmt_size(vtype: str) -> tuple[str, int]:
    _map = {
        "Int8":   ("<b", 1), "UInt8":  ("<B", 1),
        "Int16":  ("<h", 2), "UInt16": ("<H", 2),
        "Int32":  ("<i", 4), "UInt32": ("<I", 4),
        "Int64":  ("<q", 8), "UInt64": ("<Q", 8),
        "Float":  ("<f", 4), "Double": ("<d", 8),
    }
    return _map[vtype]


def _values_equal(a, b, vtype: str) -> bool:
    if vtype in ("Float", "Double"):
        # Float precision: allow tiny epsilon from pack/unpack roundtrip
        fmt, _ = _get_fmt_size(vtype)
        packed_b = struct.pack(fmt, b)
        repacked = struct.unpack(fmt, packed_b)[0]
        return abs(a - repacked) < 1e-6
    return a == b
