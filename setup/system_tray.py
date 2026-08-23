#!/usr/bin/env python3
"""FOL System Tray Icon — quick access to FOL from the system tray.

Features:
  - Status indicator (green = running, red = stopped)
  - Start/Stop all services
  - Open GUI launcher
  - Open web UI
  - Quick API key status
  - Exit FOL

Requirements:
    pip install pystray Pillow

Usage:
    python3 setup/system_tray.py              # run tray icon
    python3 setup/system_tray.py --no-gui     # tray only (no GUI window)
"""

from __future__ import annotations

import os
import sys
import subprocess
import threading
import time
import io
from typing import Any

# Add project root to path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "fol"))

# ---------------------------------------------------------------------------
# Try to import pystray
# ---------------------------------------------------------------------------

try:
    import pystray
    from pystray import MenuItem, Icon
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ---------------------------------------------------------------------------
# Port checker
# ---------------------------------------------------------------------------

def is_port_open(port: int) -> bool:
    """Check if a port is in use."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("localhost", port)) == 0
    except Exception:
        return False


def get_service_status() -> dict[str, bool]:
    """Get status of all FOL services."""
    return {
        "Orchestrator:8420": is_port_open(8420),
        "Agent Server:8421": is_port_open(8421),
        "FOL API:8754": is_port_open(8754),
        "Web UI:3000": is_port_open(3000),
    }


def any_running() -> bool:
    """Check if any FOL service is running."""
    return any(is_port_open(p) for p in [8420, 8421, 8754, 3000])


def get_python() -> str:
    """Get the Python executable path."""
    return sys.executable or "python3"


# ---------------------------------------------------------------------------
# Icon generation
# ---------------------------------------------------------------------------

def create_icon_image(running: bool = True) -> Any:
    """Create a simple tray icon image.

    Green circle = running, Red circle = stopped.
    Falls back to a colored square if Pillow is not available.
    """
    if not HAS_PIL:
        return None

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Circle
    color = (46, 204, 113, 255) if running else (231, 76, 60, 255)  # green / red
    margin = 4
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)

    # Inner dot
    center = size // 2
    dot_color = (255, 255, 255, 200)
    draw.ellipse([center - 6, center - 6, center + 6, center + 6], fill=dot_color)

    return img


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------

def start_all_services():
    """Start all FOL services."""
    for port, name, cmd in [
        (8420, "Orchestrator", ["python3", "orchestrator/server.py"]),
        (8421, "Agent Server", ["python3", "agent-server/server.py"]),
        (8754, "FOL API", ["python3", "fol/main.py"]),
    ]:
        if not is_port_open(port):
            cmd[0] = get_python()
            try:
                log_dir = os.path.join(_PROJECT_ROOT, "logs")
                os.makedirs(log_dir, exist_ok=True)
                log_file = open(os.path.join(log_dir, f"{name.lower().replace(' ', '_')}.log"), "a")
                subprocess.Popen(
                    cmd, cwd=_PROJECT_ROOT,
                    stdout=log_file, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except Exception:
                pass


def stop_all_services():
    """Stop all FOL services."""
    for port in [8420, 8421, 8754, 3000]:
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(("localhost", port)) == 0:
                    # Port is open — find and kill the process
                    import signal
                    if sys.platform == "darwin" or sys.platform.startswith("linux"):
                        result = subprocess.run(
                            ["lsof", "-ti", f":{port}"],
                            capture_output=True, text=True,
                        )
                        for pid in result.stdout.strip().split():
                            try:
                                os.kill(int(pid), signal.SIGTERM)
                            except (ProcessLookupError, ValueError):
                                pass
                    elif sys.platform == "win32":
                        result = subprocess.run(
                            ["netstat", "-ano"],
                            capture_output=True, text=True,
                        )
                        for line in result.stdout.splitlines():
                            if f":{port}" in line and "LISTENING" in line:
                                parts = line.split()
                                if parts:
                                    try:
                                        subprocess.run(
                                            ["taskkill", "/PID", parts[-1], "/F"],
                                            capture_output=True,
                                        )
                                    except Exception:
                                        pass
        except Exception:
            pass


def open_url(url: str):
    """Open a URL in the default browser."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", url])
        elif sys.platform == "win32":
            os.startfile(url)
        else:
            subprocess.Popen(["xdg-open", url])
    except Exception:
        pass


def open_gui():
    """Open the GUI launcher."""
    gui_script = os.path.join(_PROJECT_ROOT, "setup", "gui_launcher.py")
    try:
        if sys.platform == "win32":
            subprocess.Popen(["start", "cmd", "/k", get_python(), gui_script], shell=True)
        else:
            subprocess.Popen([get_python(), gui_script])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------

class FOLTrayIcon:
    """System tray icon for FOL."""

    def __init__(self):
        self._icon: Any = None
        self._running = True
        self._update_thread: threading.Thread | None = None

    def _build_menu(self) -> Any:
        """Build the tray context menu."""
        status = get_service_status()
        running = any_running()

        # Status items (non-clickable)
        menu_items = []

        # Header
        menu_items.append(MenuItem(
            f"🧠 FOL — {'Running' if running else 'Stopped'}",
            None, enabled=False,
        ))
        menu_items.append(MenuItem("─" * 30, None, enabled=False))

        # Service status
        for svc, is_running in status.items():
            icon = "🟢" if is_running else "🔴"
            menu_items.append(MenuItem(
                f"{icon} {svc}",
                None, enabled=False,
            ))

        menu_items.append(MenuItem("─" * 30, None, enabled=False))

        # Actions
        menu_items.append(MenuItem("▶ Start All Services", self._on_start_all))
        menu_items.append(MenuItem("■ Stop All Services", self._on_stop_all))
        menu_items.append(MenuItem("─" * 30, None, enabled=False))

        # Quick links
        menu_items.append(MenuItem("🌐 Open Web UI", self._on_open_web))
        menu_items.append(MenuItem("🖥 Open GUI Launcher", self._on_open_gui))
        menu_items.append(MenuItem("─" * 30, None, enabled=False))

        # Refresh
        menu_items.append(MenuItem("🔄 Refresh Status", self._on_refresh))
        menu_items.append(MenuItem("─" * 30, None, enabled=False))

        # Exit
        menu_items.append(MenuItem("❌ Exit", self._on_exit))

        return pystray.Menu(*menu_items)

    def _on_start_all(self, icon, item):
        """Start all services."""
        start_all_services()
        self._update_icon()

    def _on_stop_all(self, icon, item):
        """Stop all services."""
        stop_all_services()
        self._update_icon()

    def _on_open_web(self, icon, item):
        """Open web UI in browser."""
        open_url("http://localhost:3000")

    def _on_open_gui(self, icon, item):
        """Open the GUI launcher."""
        open_gui()

    def _on_refresh(self, icon, item):
        """Refresh status."""
        self._update_icon()

    def _on_exit(self, icon, item):
        """Exit the tray icon."""
        self._running = False
        icon.stop()

    def _update_icon(self):
        """Update the tray icon based on service status."""
        if self._icon is None:
            return
        running = any_running()
        img = create_icon_image(running)
        if img:
            self._icon.icon = img
        self._icon.menu = self._build_menu()

    def _periodic_update(self):
        """Periodically update the icon status."""
        while self._running:
            time.sleep(5)
            if self._icon and self._running:
                self._update_icon()

    def run(self):
        """Run the system tray icon."""
        if not HAS_PYSTRAY:
            print("❌ pystray is not installed.")
            print("   Install: pip install pystray Pillow")
            print()
            print("   Falling back to terminal mode...")
            self._run_terminal_mode()
            return

        if not HAS_PIL:
            print("⚠️ Pillow is not installed (pip install Pillow)")
            print("   Using default icon")

        running = any_running()
        img = create_icon_image(running)

        self._icon = Icon(
            "FOL",
            img,
            "FOL — Personal AI Assistant",
            self._build_menu(),
        )

        # Start periodic update thread
        self._update_thread = threading.Thread(target=self._periodic_update, daemon=True)
        self._update_thread.start()

        # Run the icon
        self._icon.run()

    def _run_terminal_mode(self):
        """Fallback terminal mode when pystray is not available."""
        print("\n🧠 FOL System Tray (Terminal Mode)\n")
        print("Commands:")
        print("  status  — show service status")
        print("  start   — start all services")
        print("  stop    — stop all services")
        print("  web     — open web UI")
        print("  gui     — open GUI launcher")
        print("  quit    — exit")
        print()

        while self._running:
            try:
                cmd = input("fol> ").strip().lower()
                if cmd == "status":
                    for svc, running in get_service_status().items():
                        icon = "🟢" if running else "🔴"
                        print(f"  {icon} {svc}")
                elif cmd == "start":
                    start_all_services()
                    print("  ✅ Starting services...")
                elif cmd == "stop":
                    stop_all_services()
                    print("  ⏹ Stopping services...")
                elif cmd == "web":
                    open_url("http://localhost:3000")
                elif cmd == "gui":
                    open_gui()
                elif cmd in ("quit", "exit", "q"):
                    self._running = False
                elif cmd:
                    print(f"  Unknown command: {cmd}")
            except (KeyboardInterrupt, EOFError):
                self._running = False
                break

        print("\n👋 Bye!")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Launch the FOL system tray icon."""
    import argparse
    parser = argparse.ArgumentParser(description="FOL System Tray Icon")
    parser.add_argument("--no-gui", action="store_true", help="Don't open GUI on start")
    args = parser.parse_args()

    tray = FOLTrayIcon()
    tray.run()


if __name__ == "__main__":
    main()
