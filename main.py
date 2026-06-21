"""
MemEd entry point.
Detects the current platform and launches the appropriate app.
"""

import sys
import os

# Ensure the repo root (containing the memed/ package) is on sys.path
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)


def main():
    if sys.platform == "win32":
        from memed.app import main as run
    elif sys.platform.startswith("linux"):
        from memed.platforms.linux.app import main as run
    else:
        print(f"Unsupported platform: {sys.platform}")
        sys.exit(1)

    run()


if __name__ == "__main__":
    main()
