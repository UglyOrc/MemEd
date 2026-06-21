# MemEd

A Cheat Engine-style process memory editor built with Python and tkinter.  
Supports scanning, editing, and freezing memory values in running processes.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Features

- **Memory Scanning** — First scan and next scan with 11 comparison modes:
  - Exact Value, Not Equal, Greater Than, Less Than, Between
  - Changed, Unchanged, Increased, Decreased, Increased By, Decreased By, Unknown Initial
- **Value Types** — Int8, Int16, Int32, Int64, UInt8, UInt16, UInt32, UInt64, Float, Double
- **Address Table** — Save found addresses with descriptions for quick access
- **Memory Freeze** — Lock values in place with Safe Mode and Write Verify protection
- **Save / Load** — Export and import address lists as `.memed` JSON files
- **High Performance** — NumPy-vectorised scan engine with multi-threaded region reads
- **Cross-platform** — Windows (full features) and Linux (`/proc/PID/mem`)
- **Stealth Mode** *(Windows only)* — Minimal access rights, NT direct read/write, debug flag clearing, window hiding

---

## Project Structure

```
MemEd/
├── main.py                     # Entry point — auto-detects platform
├── run.bat                     # Windows launcher (auto-requests Admin)
├── run.sh                      # Linux launcher
├── requirements.txt
├── README.md
├── .gitignore
└── memed/                      # Main package
    ├── __init__.py
    ├── app.py                  # GUI (tkinter) — Windows
    ├── memory_engine.py        # Scan engine — Windows (ctypes / WinAPI)
    ├── stealth.py              # Anti-detection techniques — Windows
    ├── freeze_manager.py       # Safe freeze loop (cross-platform)
    ├── address_file.py         # Save/load .memed files (cross-platform)
    └── platforms/
        └── linux/
            ├── app.py          # GUI — Linux (same UI, Linux-aware messages)
            ├── memory_engine.py # Scan engine — Linux (/proc/PID/mem)
            └── stealth.py      # Stealth stub — no-ops on Linux
```

---

## Requirements

- Python 3.10+
- `numpy` (see `requirements.txt`)
- tkinter (usually bundled with Python; on Linux: `sudo apt install python3-tk`)

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Usage

### Windows

Run as Administrator (required to read other process memory):

```bat
run.bat
```

Or manually:

```bash
python main.py
```

### Linux

Requires permission to access `/proc/<pid>/mem`.

**Option 1 — Run as root:**
```bash
sudo python3 main.py
```

**Option 2 — Relax ptrace scope (persists until reboot):**
```bash
sudo sysctl kernel.yama.ptrace_scope=0
python3 main.py
```

Or use the launcher:
```bash
chmod +x run.sh
./run.sh
```

---

## How to Use

1. Click **+ Open Process** and select the target process
2. Choose a **Value Type** and **Comparison** mode
3. Enter a value and click **New Scan**
4. Change the value in-game, then click **Next Scan** to narrow results
5. Double-click a result to add it to the **Address Table**
6. Click **Freeze** to lock the value in place

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `F11` | Pause / Resume all freezes |
| `F12` | Emergency unfreeze all |
| `Ctrl+S` | Save address list |
| `Ctrl+O` | Load address list |
| `Enter` | Smart scan (New or Next) |
| `Delete` | Remove selected address row |

---

## Stealth Features *(Windows only)*

Accessible via the **Stealth** menu:

| Feature | Description |
|---------|-------------|
| Minimal Access Rights | Opens process with `VM_READ/WRITE` instead of `PROCESS_ALL_ACCESS` |
| Clear PEB Debug Flag | Makes `IsDebuggerPresent()` return false in the target |
| NT Direct Read/Write | Calls `NtReadVirtualMemory` directly, bypassing kernel32 hooks |
| Hide Window | Excludes MemEd from screen-capture APIs |
| Random Scan Delay | Adds 1–5ms jitter between region reads to defeat timing heuristics |

---

## Freeze Safety

| Option | Description |
|--------|-------------|
| Safe Mode | Reads current value before writing — skips write if already correct |
| Write Verify | Reads back after each write — auto-disables after 3 consecutive failures |
| Adjustable Interval | 50ms (aggressive) to 2000ms (safe) |
| Emergency Pause | `F11` stops all writes instantly without clearing the list |
| Emergency Unfreeze | `F12` clears all freezes immediately |

---

## Building a Windows Executable

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name MemEd main.py
```

Output will be in `dist/MemEd.exe`.

---

## License

MIT License — free to use, modify, and distribute.
