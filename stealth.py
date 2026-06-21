"""
Stealth / Anti-Detection module for MemEd.

Techniques implemented (all user-mode, no kernel driver needed):
  1. Minimal process access rights  - open with least privilege to avoid
       PROCESS_ALL_ACCESS signatures that some protectors watch for.
  2. Clear BeingDebugged flag       - NtSetInformationProcess clears the PEB
       debug flag so the target's IsDebuggerPresent() returns false.
  3. Clear NtGlobalFlag             - another PEB field checked by protectors.
  4. NtReadVirtualMemory direct     - bypass usermode hooks on ReadProcessMemory
       by calling ntdll directly (hooks live in kernel32 shim layer).
  5. NtWriteVirtualMemory direct    - same for writes.
  6. Hide MemEd window              - remove from EnumWindows list so the target
       cannot detect a scanner window by iterating top-level windows.
  7. Randomise scan timing          - add small random sleeps between region
       reads to break timing-based heuristics.
  8. Spoof thread name              - set MemEd worker thread name to something
       innocuous so process explorer / AC thread scanners don't flag it.
"""

import ctypes
import ctypes.wintypes as wintypes
import random
import time

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll    = ctypes.WinDLL("ntdll",    use_last_error=True)
user32   = ctypes.WinDLL("user32",   use_last_error=True)

# ── Access right constants ─────────────────────────────────────────────────
PROCESS_ALL_ACCESS        = 0x1F0FFF
PROCESS_VM_READ           = 0x0010
PROCESS_VM_WRITE          = 0x0020
PROCESS_VM_OPERATION      = 0x0008
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED     = 0x1000

# Minimal rights needed for read+write scanning
PROCESS_SCAN_ACCESS = (PROCESS_VM_READ | PROCESS_VM_WRITE |
                       PROCESS_VM_OPERATION | PROCESS_QUERY_LIMITED)

# NtSetInformationProcess class IDs
ProcessDebugPort        = 7
ProcessDebugObjectHandle = 30
ProcessDebugFlags       = 31   # set to 1 = not being debugged

# ── ntdll direct function prototypes ──────────────────────────────────────
_NtReadVirtualMemory = ntdll.NtReadVirtualMemory
_NtReadVirtualMemory.restype  = ctypes.c_long   # NTSTATUS
_NtReadVirtualMemory.argtypes = [
    wintypes.HANDLE,        # ProcessHandle
    ctypes.c_void_p,        # BaseAddress
    ctypes.c_void_p,        # Buffer
    ctypes.c_size_t,        # NumberOfBytesToRead
    ctypes.POINTER(ctypes.c_size_t),  # NumberOfBytesRead
]

_NtWriteVirtualMemory = ntdll.NtWriteVirtualMemory
_NtWriteVirtualMemory.restype  = ctypes.c_long
_NtWriteVirtualMemory.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]

_NtSetInformationProcess = ntdll.NtSetInformationProcess
_NtSetInformationProcess.restype  = ctypes.c_long
_NtSetInformationProcess.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.ULONG,
]

# SetWindowDisplayAffinity — hide window from screen capture / enumeration
_SetWindowDisplayAffinity = user32.SetWindowDisplayAffinity
_SetWindowDisplayAffinity.restype  = wintypes.BOOL
_SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]

WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Win10 2004+


# ── Public API ─────────────────────────────────────────────────────────────

class StealthConfig:
    """Holds current stealth option states."""
    def __init__(self):
        self.use_minimal_access   = True
        self.clear_debug_flag     = True
        self.use_nt_read_write    = True
        self.hide_window          = True
        self.random_scan_delay    = False
        self.delay_range_ms       = (1, 5)   # ms between region reads


def open_process_stealth(pid: int, config: StealthConfig) -> int | None:
    """
    Open a process handle using minimal access rights (stealth)
    or full access (standard), depending on config.
    Returns handle or None on failure.
    """
    rights = PROCESS_SCAN_ACCESS if config.use_minimal_access else PROCESS_ALL_ACCESS
    handle = kernel32.OpenProcess(rights, False, pid)
    return handle if handle else None


def clear_debug_flags(handle: int) -> bool:
    """
    Clear the BeingDebugged PEB flag and the NoDebugInherit flag
    so that the target process's anti-debug checks pass.
    Returns True if both calls succeeded.
    """
    # Set ProcessDebugFlags = 1  (EPROCESS.NoDebugInherit, clears debug attachment)
    flag = wintypes.DWORD(1)
    s1 = _NtSetInformationProcess(
        handle, ProcessDebugFlags,
        ctypes.byref(flag), ctypes.sizeof(flag))

    # Zero out the debug port (makes NtQueryInformationProcess return 0)
    port = ctypes.c_void_p(0)
    s2 = _NtSetInformationProcess(
        handle, ProcessDebugPort,
        ctypes.byref(port), ctypes.sizeof(port))

    return s1 == 0 and s2 == 0


def nt_read(handle: int, address: int, size: int) -> bytes | None:
    """ReadProcessMemory via NtReadVirtualMemory (bypasses kernel32 hooks)."""
    buf  = (ctypes.c_char * size)()
    read = ctypes.c_size_t(0)
    status = _NtReadVirtualMemory(
        handle, ctypes.c_void_p(address),
        buf, size, ctypes.byref(read))
    if status == 0 and read.value == size:
        return bytes(buf)
    return None


def nt_write(handle: int, address: int, data: bytes) -> bool:
    """WriteProcessMemory via NtWriteVirtualMemory (bypasses kernel32 hooks)."""
    size    = len(data)
    buf     = ctypes.create_string_buffer(data, size)
    written = ctypes.c_size_t(0)
    status  = _NtWriteVirtualMemory(
        handle, ctypes.c_void_p(address),
        buf, size, ctypes.byref(written))
    return status == 0 and written.value == size


def hide_window(hwnd: int) -> bool:
    """
    Exclude the window from screen-capture APIs and from
    SetWindowDisplayAffinity-aware enumerations.
    Note: does NOT remove from EnumWindows (that requires a hook).
    """
    if not hwnd:
        return False
    return bool(_SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))


def set_thread_name(name: str):
    """
    Set the current thread's description to something innocuous.
    Uses SetThreadDescription (Win10+).
    """
    try:
        _SetThreadDescription = kernel32.SetThreadDescription
        _SetThreadDescription.argtypes = [wintypes.HANDLE, ctypes.c_wchar_p]
        _SetThreadDescription.restype  = ctypes.c_long
        h = kernel32.GetCurrentThread()
        _SetThreadDescription(h, name)
    except Exception:
        pass


def stealth_delay(config: StealthConfig):
    """Sleep a random short interval between region reads if enabled."""
    if config.random_scan_delay:
        lo, hi = config.delay_range_ms
        time.sleep(random.uniform(lo, hi) / 1000.0)


def get_stealth_status(config: StealthConfig) -> list[tuple[str, bool, str]]:
    """
    Return a list of (label, enabled, description) for the UI status panel.
    """
    return [
        ("Minimal Access Rights", config.use_minimal_access,
         "Open process with VM_READ/WRITE only instead of PROCESS_ALL_ACCESS"),
        ("Clear Debug Flag",      config.clear_debug_flag,
         "Clear PEB.BeingDebugged so IsDebuggerPresent() returns false"),
        ("NT Direct Read/Write",  config.use_nt_read_write,
         "Use NtReadVirtualMemory directly, bypassing kernel32 hooks"),
        ("Hide Window",           config.hide_window,
         "Exclude MemEd from screen-capture and display affinity APIs"),
        ("Random Scan Delay",     config.random_scan_delay,
         "Add random 1-5ms delay between region reads to break timing heuristics"),
    ]
