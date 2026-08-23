#!/usr/bin/env python3
"""FOL System Dependency Installer — auto-installs OS-level packages.

Detects the current platform and installs required system dependencies:
  - macOS:   brew install
  - Ubuntu/Debian: apt install
  - Fedora/RHEL: dnf install
  - Arch: pacman -S
  - Windows: choco install (if Chocolatey available)

Also installs Python packages from requirements.txt.

Usage:
    python3 setup/install_deps.py           # install everything
    python3 setup/install_deps.py --check   # only check what's missing
    python3 setup/install_deps.py --python  # only install Python deps
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    RED     = "\033[31m"
    CYAN    = "\033[36m"

def ok(msg):   print(f"  {C.GREEN}✅{C.RESET} {msg}")
def warn(msg): print(f"  {C.YELLOW}⚠️{C.RESET} {msg}")
def fail(msg): print(f"  {C.RED}❌{C.RESET} {msg}")
def info(msg): print(f"  {C.CYAN}ℹ️{C.RESET} {msg}")

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform() -> str:
    """Detect the OS and package manager."""
    if sys.platform == "darwin":
        return "macos"
    elif sys.platform == "win32":
        return "windows"
    elif sys.platform.startswith("linux"):
        # Detect distro
        if os.path.isfile("/etc/os-release"):
            with open("/etc/os-release") as f:
                content = f.read().lower()
                if "ubuntu" in content or "debian" in content or "mint" in content:
                    return "debian"
                elif "fedora" in content or "rhel" in content or "centos" in content:
                    return "fedora"
                elif "arch" in content or "manjaro" in content:
                    return "arch"
        return "linux"
    return "unknown"


def find_package_manager() -> str | None:
    """Find the available package manager."""
    for pm in ["apt", "apt-get", "dnf", "yum", "pacman", "brew", "choco"]:
        if shutil.which(pm):
            return pm
    return None

# ---------------------------------------------------------------------------
# Dependency definitions
# ---------------------------------------------------------------------------

# System packages needed per platform
SYSTEM_DEPS: dict[str, list[str]] = {
    "macos": [
        # "ffmpeg",  # for audio/video conversion
        "tmux",       # for freebuff tmux bridge
    ],
    "debian": [
        "python3-pip",
        "python3-venv",
        "python3-tk",        # tkinter for GUI launcher
        "ffmpeg",            # audio/video conversion
        "scrot",             # screenshots
        "xdotool",           # window detection
        "espeak-ng",         # TTS
        "libnotify-bin",     # desktop notifications
        "pulseaudio",        # audio input
        "alsa-utils",        # audio utilities
        "libasound2-dev",    # audio dev headers (for pyaudio)
        "build-essential",   # compilation tools
    ],
    "fedora": [
        "python3-pip",
        "python3-tkinter",
        "ffmpeg",
        "scrot",
        "xdotool",
        "espeak-ng",
        "libnotify",
        "pulseaudio-utils",
        "alsa-utils",
        "alsa-lib-devel",
        "gcc",
        "python3-devel",
    ],
    "arch": [
        "python-pip",
        "python-tk",
        "ffmpeg",
        "scrot",
        "xdotool",
        "espeak-ng",
        "libnotify",
        "pulseaudio",
        "alsa-utils",
        "base-devel",
    ],
    "windows": [
        # Windows: use choco if available, otherwise manual
        "ffmpeg",
        "python",    # should already be installed
    ],
}

# Python packages that need system-level build tools
PYTHON_BUILD_DEPS = {
    "debian": ["build-essential", "python3-dev", "libasound2-dev"],
    "fedora": ["gcc", "python3-devel", "alsa-lib-devel"],
    "arch": ["base-devel", "python"],
    "macos": [],  # Xcode CLT handles this
    "windows": [],
}

# ---------------------------------------------------------------------------
# Package manager commands
# ---------------------------------------------------------------------------

def get_install_cmd(pm: str, packages: list[str]) -> list[str]:
    """Get the install command for a package manager."""
    if pm in ("apt", "apt-get"):
        return ["sudo", pm, "install", "-y"] + packages
    elif pm == "dnf":
        return ["sudo", "dnf", "install", "-y"] + packages
    elif pm == "yum":
        return ["sudo", "yum", "install", "-y"] + packages
    elif pm == "pacman":
        return ["sudo", "pacman", "-S", "--noconfirm"] + packages
    elif pm == "brew":
        return ["brew", "install"] + packages
    elif pm == "choco":
        return ["choco", "install", "-y"] + packages
    return []


# ---------------------------------------------------------------------------
# Install logic
# ---------------------------------------------------------------------------

def check_installed(commands: list[str]) -> tuple[list[str], list[str]]:
    """Check which commands are installed and which are missing.

    Returns (installed, missing) lists.
    """
    installed = []
    missing = []
    for cmd in commands:
        if shutil.which(cmd):
            installed.append(cmd)
        else:
            missing.append(cmd)
    return installed, missing


def install_system_deps(platform_name: str, pm: str | None, check_only: bool = False) -> bool:
    """Install system dependencies for the current platform."""
    deps = SYSTEM_DEPS.get(platform_name, [])
    if not deps:
        info("No system dependencies to install for this platform")
        return True

    print(f"\n{C.BOLD}System Dependencies ({platform_name}):{C.RESET}\n")

    # Check what's already installed
    installed, missing = check_installed(deps)
    if installed:
        ok(f"Already installed: {', '.join(installed)}")

    if not missing:
        ok("All system dependencies are installed!")
        return True

    warn(f"Missing: {', '.join(missing)}")

    if check_only:
        return False

    if not pm:
        fail("No package manager found. Install manually:")
        for pkg in missing:
            print(f"    {pkg}")
        return False

    print(f"\n{C.BOLD}Installing with {pm}...{C.RESET}\n")

    # Filter out packages that are commands vs package names
    # (some deps are package names, not command names)
    pkgs_to_install = []
    for pkg in missing:
        # Map command names to package names
        pkg_name = _cmd_to_package(pkg, platform_name, pm)
        if pkg_name and pkg_name not in pkgs_to_install:
            pkgs_to_install.append(pkg_name)

    if not pkgs_to_install:
        warn("No packages to install")
        return True

    cmd = get_install_cmd(pm, pkgs_to_install)
    info(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            ok(f"Installed: {', '.join(pkgs_to_install)}")
            return True
        else:
            fail(f"Installation failed (exit code {result.returncode})")
            if result.stderr:
                print(f"    {result.stderr[:500]}")
            return False
    except subprocess.TimeoutExpired:
        fail("Installation timed out (5 minutes)")
        return False
    except Exception as exc:
        fail(f"Installation error: {exc}")
        return False


def _cmd_to_package(cmd: str, platform_name: str, pm: str) -> str | None:
    """Map a command name to the correct package name for the package manager."""
    # Mapping: command → {platform: package_name}
    mapping: dict[str, dict[str, str]] = {
        "ffmpeg": {"debian": "ffmpeg", "fedora": "ffmpeg", "arch": "ffmpeg", "macos": "ffmpeg", "windows": "ffmpeg"},
        "tmux": {"debian": "tmux", "fedora": "tmux", "arch": "tmux", "macos": "tmux"},
        "scrot": {"debian": "scrot", "fedora": "scrot", "arch": "scrot"},
        "xdotool": {"debian": "xdotool", "fedora": "xdotool", "arch": "xdotool"},
        "espeak-ng": {"debian": "espeak-ng", "fedora": "espeak-ng", "arch": "espeak-ng"},
        "espeak": {"debian": "espeak", "fedora": "espeak", "arch": "espeak"},
        "notify-send": {"debian": "libnotify-bin", "fedora": "libnotify", "arch": "libnotify"},
        "pactl": {"debian": "pulseaudio", "fedora": "pulseaudio-utils", "arch": "pulseaudio"},
        "arecord": {"debian": "alsa-utils", "fedora": "alsa-utils", "arch": "alsa-utils"},
        "python3": {"debian": "python3", "fedora": "python3", "arch": "python"},
        "pip3": {"debian": "python3-pip", "fedora": "python3-pip", "arch": "python-pip"},
        "python3-tk": {"debian": "python3-tk", "fedora": "python3-tkinter", "arch": "python-tk"},
    }

    if cmd in mapping:
        return mapping[cmd].get(platform_name, cmd)
    return cmd


def install_python_deps(check_only: bool = False) -> bool:
    """Install Python dependencies from requirements.txt."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    req_file = os.path.join(project_root, "requirements.txt")

    if not os.path.isfile(req_file):
        warn("requirements.txt not found")
        return True

    print(f"\n{C.BOLD}Python Dependencies:{C.RESET}\n")

    if check_only:
        info(f"Would install from: {req_file}")
        return True

    python = sys.executable or "python3"
    info(f"Running: {python} -m pip install -r {req_file}")

    try:
        result = subprocess.run(
            [python, "-m", "pip", "install", "-r", req_file, "--quiet"],
            capture_output=True, text=True, cwd=project_root, timeout=300,
        )
        if result.returncode == 0:
            ok("Python dependencies installed")
            return True
        else:
            warn(f"Pip warnings: {result.stderr[:300]}")
            return True  # Partial success is OK
    except Exception as exc:
        fail(f"Python install error: {exc}")
        return False


def verify_installation() -> dict[str, bool]:
    """Verify all critical tools are available."""
    checks = {
        "Python 3": shutil.which("python3") or shutil.which("python"),
        "pip": shutil.which("pip3") or shutil.which("pip"),
        "FFmpeg": shutil.which("ffmpeg"),
        "tmux": shutil.which("tmux"),
        "scrot/maim": shutil.which("scrot") or shutil.which("maim"),
        "xdotool": shutil.which("xdotool"),
        "espeak-ng": shutil.which("espeak-ng") or shutil.which("espeak"),
        "notify-send": shutil.which("notify-send"),
    }
    return checks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FOL System Dependency Installer")
    parser.add_argument("--check", action="store_true", help="Only check what's missing")
    parser.add_argument("--python", action="store_true", help="Only install Python dependencies")
    parser.add_argument("--skip-python", action="store_true", help="Skip Python dependencies")
    parser.add_argument("--verify", action="store_true", help="Verify installation")
    args = parser.parse_args()

    platform_name = detect_platform()
    pm = find_package_manager()

    print(f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════╗
║  📦 FOL Dependency Installer                        ║
╚══════════════════════════════════════════════════════╝{C.RESET}

  Platform: {C.CYAN}{platform_name}{C.RESET}
  Package manager: {C.CYAN}{pm or 'not found'}{C.RESET}
  Python: {C.CYAN}{sys.executable}{C.RESET}
""")

    # Verify mode
    if args.verify:
        print(f"{C.BOLD}Verification:{C.RESET}\n")
        checks = verify_installation()
        all_ok = True
        for tool, found in checks.items():
            if found:
                ok(f"{tool}")
            else:
                fail(f"{tool} — NOT FOUND")
                all_ok = False
        print()
        if all_ok:
            ok("All critical tools are available!")
        else:
            warn("Some tools are missing. Run without --verify to install.")
        return

    # Install system deps
    if not args.python:
        install_system_deps(platform_name, pm, check_only=args.check)

    # Install Python deps
    if not args.skip_python:
        install_python_deps(check_only=args.check)

    # Final verification
    if not args.check:
        print(f"\n{C.BOLD}Verification:{C.RESET}\n")
        checks = verify_installation()
        for tool, found in checks.items():
            if found:
                ok(f"{tool}")
            else:
                warn(f"{tool} — not installed (optional)")

    print(f"\n{C.GREEN}{C.BOLD}Done!{C.RESET}\n")


if __name__ == "__main__":
    main()
