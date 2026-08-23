#!/usr/bin/env python3
"""FOL GUI Launcher — double-click to open the control panel.

This is a convenience wrapper that imports and runs the GUI launcher.
Works on Windows, Linux, and macOS.

Usage:
    python3 launch_gui.py
    # Or just double-click this file on most systems.
"""

import os
import sys

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fol"))

# Check tkinter availability
try:
    import tkinter
except ImportError:
    print("❌ tkinter is not installed.")
    print()
    print("Install it:")
    print("  macOS:   brew install python-tk")
    print("  Ubuntu:  sudo apt install python3-tk")
    print("  Fedora:  sudo dnf install python3-tkinter")
    print("  Windows: tkinter is included with Python")
    print()
    sys.exit(1)

# Run the GUI
from setup.gui_launcher import main
main()
