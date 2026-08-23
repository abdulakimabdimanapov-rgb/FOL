#!/usr/bin/env python3
"""FOL System Tray — quick access icon in the system tray.

Double-click to start the tray icon. Right-click for options:
  - Start/Stop services
  - Open Web UI
  - Open GUI Launcher
  - Exit

Requirements:
    pip install pystray Pillow

Usage:
    python3 launch_tray.py
"""

import os
import sys

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fol"))

# Check dependencies
missing = []
try:
    import pystray
except ImportError:
    missing.append("pystray")
try:
    from PIL import Image
except ImportError:
    missing.append("Pillow")

if missing:
    print(f"❌ Missing dependencies: {', '.join(missing)}")
    print()
    print("Install them:")
    print(f"  pip install {' '.join(missing)}")
    print()
    answer = input("Install now? [Y/n] > ").strip().lower()
    if answer in ("", "y", "yes"):
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install"] + missing)
        print("\n✅ Installed! Run again: python3 launch_tray.py")
    sys.exit(1)

# Run the tray icon
from setup.system_tray import main
main()
