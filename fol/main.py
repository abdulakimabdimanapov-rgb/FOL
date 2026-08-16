"""FOL entry point.

Usage:
    # From SecondSelf/ directory:
    python fol/main.py
"""
import sys
from pathlib import Path

# Ensure `fol/` is in sys.path when running from parent directory
_fol_dir = Path(__file__).parent
if str(_fol_dir) not in sys.path:
    sys.path.insert(0, str(_fol_dir))

from core.app import main

if __name__ == "__main__":
    raise SystemExit(main())
