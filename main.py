"""
MemEd entry point.
Detects the current platform and launches the appropriate app.
"""

import sys
import os


def main():
    if sys.platform == "win32":
        # Add memed package to path so imports resolve correctly
        sys.path.insert(0, os.path.dirname(__file__))
        from memed.app import main as run
    elif sys.platform.startswith("linux"):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "memed", "platforms", "linux"))
        sys.path.insert(0, os.path.dirname(__file__))
        from memed.platforms.linux.app import main as run
    else:
        print(f"Unsupported platform: {sys.platform}")
        sys.exit(1)

    run()


if __name__ == "__main__":
    main()
