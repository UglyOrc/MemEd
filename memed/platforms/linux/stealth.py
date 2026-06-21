"""
Stealth module stub for Linux.

The Windows anti-detection techniques (NT direct calls, PEB flag clearing,
SetWindowDisplayAffinity) don't exist on Linux. This module exposes the
same API so the rest of MemEd compiles unchanged; all stealth ops are no-ops.
"""
from __future__ import annotations

import random
import time


class StealthConfig:
    def __init__(self):
        self.use_minimal_access   = False  # no-op on Linux (ptrace always needs perms)
        self.clear_debug_flag     = False  # no-op on Linux
        self.use_nt_read_write    = False  # no-op on Linux
        self.hide_window          = False  # no-op on Linux
        self.random_scan_delay    = False
        self.delay_range_ms       = (1, 5)


def open_process_stealth(pid: int, config: StealthConfig) -> int | None:
    """On Linux we just return the PID itself as a pseudo-handle."""
    import os
    try:
        os.kill(pid, 0)  # check process exists
        return pid
    except (ProcessLookupError, PermissionError):
        return None


def clear_debug_flags(handle: int) -> bool:
    return False  # not applicable


def nt_read(handle: int, address: int, size: int) -> bytes | None:
    return None  # not used on Linux


def nt_write(handle: int, address: int, data: bytes) -> bool:
    return False  # not used on Linux


def hide_window(hwnd: int) -> bool:
    return False


def set_thread_name(name: str):
    pass


def stealth_delay(config: StealthConfig):
    if config.random_scan_delay:
        lo, hi = config.delay_range_ms
        time.sleep(random.uniform(lo, hi) / 1000.0)


def get_stealth_status(config: StealthConfig) -> list[tuple[str, bool, str]]:
    return [
        ("Minimal Access Rights", False, "Not applicable on Linux"),
        ("Clear Debug Flag",      False, "Not applicable on Linux"),
        ("NT Direct Read/Write",  False, "Not applicable on Linux"),
        ("Hide Window",           False, "Not applicable on Linux"),
        ("Random Scan Delay",     config.random_scan_delay,
         "Add random 1-5ms delay between region reads"),
    ]
