#!/usr/bin/env python3
"""FOL GUI Launcher — Cross-platform control panel for Windows/Linux/macOS.

Features:
  - Start/Stop individual services (Orchestrator, Agent, FOL API, Web UI)
  - Real-time service status with color indicators
  - API key configuration with validation
  - STT provider selection (mlx_whisper / groq / elevenlabs)
  - Brain backend selection (current / freebuff)
  - Live log viewer with auto-scroll
  - Dark/Light theme toggle
  - One-click setup wizard

Usage:
    python3 setup/gui_launcher.py
"""

from __future__ import annotations

import os
import sys
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Any

# Add project root to path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "fol"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_TITLE = "🧠 FOL — Personal AI Assistant"
APP_WIDTH = 900
APP_HEIGHT = 700

SERVICES = {
    "orchestrator": {"name": "Orchestrator", "port": 8420, "cmd": ["python3", "orchestrator/server.py"]},
    "agent": {"name": "Agent Server", "port": 8421, "cmd": ["python3", "agent-server/server.py"]},
    "fol_api": {"name": "FOL API", "port": 8754, "cmd": ["python3", "fol/main.py"]},
    "web": {"name": "Web UI", "port": 3000, "cmd": ["npm", "run", "dev"]},
}

BRAIN_OPTIONS = {
    "current": "API Keys (LiteLLM — OpenAI, Anthropic, Groq, etc.)",
    "freebuff": "Freebuff (DeepSeek V4, MiMo 2.5 via OpenRouter)",
}

STT_OPTIONS = {
    "mlx_whisper": "Local MLX Whisper (Apple Silicon, offline)",
    "groq": "Groq Whisper (cloud, free, fast)",
    "elevenlabs": "ElevenLabs Scribe (cloud, paid)",
}

PROVIDERS = {
    "OPENAI_API_KEY": "OpenAI (GPT-4o)",
    "ANTHROPIC_API_KEY": "Anthropic (Claude)",
    "GEMINI_API_KEY": "Google Gemini",
    "OPENROUTER_API_KEY": "OpenRouter (100+ models)",
    "DEEPSEEK_API_KEY": "DeepSeek",
    "GROQ_API_KEY": "Groq (free tier)",
    "XAI_API_KEY": "xAI (Grok)",
    "ELEVENLABS_API_KEY": "ElevenLabs (TTS/STT)",
    "TAVILY_API_KEY": "Tavily (web search)",
}


# ---------------------------------------------------------------------------
# Color palettes
# ---------------------------------------------------------------------------

THEMES = {
    "dark": {
        "bg":           "#1a1b26",   # main background
        "bg_light":     "#24283b",   # card/panel background
        "bg_entry":     "#2f3347",   # entry field background
        "bg_hover":     "#3b4261",   # hover state
        "fg":           "#c0caf5",   # main text
        "fg_dim":       "#565f89",   # dimmed text
        "fg_bright":    "#e0e6ff",   # bright text
        "accent":       "#7aa2f7",   # blue accent
        "accent2":      "#bb9af7",   # purple accent
        "green":        "#9ece6a",   # success / running
        "red":          "#f7768e",   # error / stopped
        "yellow":       "#e0af68",   # warning
        "orange":       "#ff9e64",   # orange accent
        "border":       "#3b4261",   # borders
        "select":       "#33467c",   # selection highlight
        "log_bg":       "#16161e",   # log viewer background
        "log_fg":       "#a9b1d6",   # log viewer text
    },
    "light": {
        "bg":           "#f5f5f5",
        "bg_light":     "#ffffff",
        "bg_entry":     "#ffffff",
        "bg_hover":     "#e8e8e8",
        "fg":           "#333333",
        "fg_dim":       "#888888",
        "fg_bright":    "#111111",
        "accent":       "#2563eb",
        "accent2":      "#7c3aed",
        "green":        "#16a34a",
        "red":          "#dc2626",
        "yellow":       "#d97706",
        "orange":       "#ea580c",
        "border":       "#d1d5db",
        "select":       "#dbeafe",
        "log_bg":       "#ffffff",
        "log_fg":       "#333333",
    },
}


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def load_env() -> dict[str, str]:
    """Load .env file into a dict."""
    env = dict(os.environ)
    env_path = os.path.join(_PROJECT_ROOT, ".env")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    env[key.strip()] = val.strip()
    return env


def save_env(updates: dict[str, str]) -> None:
    """Update .env file with new values."""
    env_path = os.path.join(_PROJECT_ROOT, ".env")
    lines: list[str] = []
    updated_keys: set[str] = set()

    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                stripped = line.strip()
                matched = False
                for key, val in updates.items():
                    if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                        lines.append(f"{key}={val}\n")
                        updated_keys.add(key)
                        matched = True
                        break
                if not matched:
                    lines.append(line)

    for key, val in updates.items():
        if key not in updated_keys:
            lines.append(f"\n{key}={val}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)


def is_port_open(port: int) -> bool:
    """Check if a port is in use."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("localhost", port)) == 0


def get_python() -> str:
    """Get the Python executable path."""
    return sys.executable or "python3"


# ---------------------------------------------------------------------------
# Color interpolation for smooth transitions
# ---------------------------------------------------------------------------

def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB tuple to hex color."""
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp_color(color1: str, color2: str, t: float) -> str:
    """Linearly interpolate between two hex colors.

    t=0.0 → color1, t=1.0 → color2
    """
    r1, g1, b1 = hex_to_rgb(color1)
    r2, g2, b2 = hex_to_rgb(color2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return rgb_to_hex(r, g, b)


def lerp_theme(theme1: dict[str, str], theme2: dict[str, str], t: float) -> dict[str, str]:
    """Interpolate between two themes."""
    return {key: lerp_color(theme1[key], theme2[key], t) for key in theme1}


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------

class FOLLauncher(tk.Tk):
    """Main FOL GUI Launcher window."""

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(f"{APP_WIDTH}x{APP_HEIGHT}")
        self.minsize(800, 600)

        # State
        self.env = load_env()
        self.processes: dict[str, subprocess.Popen | None] = {}
        self._log_thread: threading.Thread | None = None
        self._running = True
        self._current_theme = self.env.get("FOL_THEME", "dark")  # load from .env
        if self._current_theme not in THEMES:
            self._current_theme = "dark"
        self._transition_active = False  # animation lock

        # Style
        self._setup_style()

        # Layout
        self._create_menu()
        self._create_main_layout()

        # Apply theme
        self._apply_theme()

        # Start status checker
        self._check_status()

        # Check for updates in background
        self.after(2000, self._background_update_check)

        # Cleanup on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_style(self):
        """Configure ttk styles."""
        style = ttk.Style()

        # Try to use a modern theme
        available = style.theme_names()
        for theme in ("clam", "alt", "default"):
            if theme in available:
                style.theme_use(theme)
                break

        # Custom styles (will be recolored by _apply_theme)
        style.configure("Title.TLabel", font=("Helvetica", 16, "bold"))
        style.configure("Header.TLabel", font=("Helvetica", 11, "bold"))
        style.configure("Status.TLabel", font=("Helvetica", 10))
        style.configure("Start.TButton", font=("Helvetica", 10, "bold"))
        style.configure("Stop.TButton", font=("Helvetica", 10))

    def _apply_theme(self):
        """Apply the current color theme to all widgets."""
        t = THEMES[self._current_theme]
        self._apply_theme_from_palette(t)

    def _apply_theme_from_palette(self, t: dict[str, str]):
        """Apply a color palette to all widgets (used by animation)."""
        style = ttk.Style()

        # Configure ttk styles with theme colors
        style.configure(".", background=t["bg"], foreground=t["fg"])
        style.configure("TFrame", background=t["bg"])
        style.configure("TLabel", background=t["bg"], foreground=t["fg"])
        style.configure("Title.TLabel", background=t["bg"], foreground=t["fg_bright"], font=("Helvetica", 16, "bold"))
        style.configure("Header.TLabel", background=t["bg"], foreground=t["fg_bright"], font=("Helvetica", 11, "bold"))
        style.configure("Status.TLabel", background=t["bg"], foreground=t["fg_dim"], font=("Helvetica", 10))

        # Buttons
        style.configure("TButton", background=t["bg_light"], foreground=t["fg"])
        style.map("TButton",
                   background=[("active", t["bg_hover"]), ("pressed", t["bg_hover"])],
                   foreground=[("active", t["fg_bright"])])
        style.configure("Start.TButton", background=t["green"], foreground="#1a1b26", font=("Helvetica", 10, "bold"))
        style.map("Start.TButton",
                   background=[("active", "#73daca"), ("pressed", "#73daca")])
        style.configure("Stop.TButton", background=t["red"], foreground="#1a1b26", font=("Helvetica", 10))
        style.map("Stop.TButton",
                   background=[("active", "#ff7a93"), ("pressed", "#ff7a93")])

        # Entry fields
        style.configure("TEntry", fieldbackground=t["bg_entry"], foreground=t["fg"],
                        insertcolor=t["fg"], borderwidth=1)
        style.map("TEntry",
                   fieldbackground=[("focus", t["bg_hover"])],
                   foreground=[("focus", t["fg_bright"])])

        # Radiobuttons
        style.configure("TRadiobutton", background=t["bg"], foreground=t["fg"])
        style.map("TRadiobutton",
                   background=[("active", t["bg_light"])],
                   foreground=[("active", t["fg_bright"])])

        # Notebook (tabs)
        style.configure("TNotebook", background=t["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=t["bg_light"], foreground=t["fg_dim"],
                        padding=[12, 6])
        style.map("TNotebook.Tab",
                   background=[("selected", t["bg_entry"])],
                   foreground=[("selected", t["accent"])])

        # LabelFrame
        style.configure("TLabelframe", background=t["bg"], foreground=t["fg_dim"])
        style.configure("TLabelframe.Label", background=t["bg"], foreground=t["accent"],
                        font=("Helvetica", 10, "bold"))

        # Scrollbar
        style.configure("TScrollbar", background=t["bg_light"], troughcolor=t["bg"])

        # Apply to main window
        self.configure(bg=t["bg"])

        # Apply to log text widget (special handling)
        if hasattr(self, "log_text"):
            self.log_text.configure(
                bg=t["log_bg"], fg=t["log_fg"],
                insertbackground=t["fg"],
                selectbackground=t["select"],
                relief="flat", borderwidth=0,
            )

    def _toggle_theme(self):
        """Toggle between dark and light theme with smooth animation."""
        new_theme = "light" if self._current_theme == "dark" else "dark"
        self._animate_theme_transition(new_theme)

    def _save_theme(self, theme: str):
        """Save theme selection to .env."""
        save_env({"FOL_THEME": theme})
        self.env["FOL_THEME"] = theme

    def _animate_theme_transition(self, target_theme: str, steps: int = 12, delay_ms: int = 25):
        """Animate a smooth transition between themes.

        Uses linear color interpolation over `steps` frames.
        Total duration: steps * delay_ms ms (e.g. 12 * 25 = 300ms).
        """
        if self._transition_active:
            return  # already transitioning

        self._transition_active = True
        from_theme = THEMES[self._current_theme]
        to_theme = THEMES[target_theme]

        def step(i: int):
            if i > steps:
                # Final: apply target theme exactly
                self._current_theme = target_theme
                self._apply_theme()
                self._transition_active = False
                self._save_theme(target_theme)
                self._log(f"🎨 Theme: {self._current_theme}")
                return

            # Ease-in-out (smooth start + smooth end)
            t = i / steps
            t = t * t * (3 - 2 * t)  # smoothstep

            # Interpolate all colors
            interpolated = lerp_theme(from_theme, to_theme, t)
            self._apply_theme_from_palette(interpolated)

            # Next frame
            self.after(delay_ms, lambda: step(i + 1))

        step(0)

    def _create_menu(self):
        """Create the top menu bar."""
        menubar = tk.Menu(self)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open .env", command=self._open_env_file)
        file_menu.add_command(label="Open project folder", command=self._open_project_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Toggle Dark/Light Theme", command=self._toggle_theme,
                              accelerator="Ctrl+T")
        menubar.add_cascade(label="View", menu=view_menu)
        self.bind("<Control-t>", lambda e: self._toggle_theme())

        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Setup Wizard", command=self._run_setup_wizard)
        tools_menu.add_command(label="Validate API Keys", command=self._validate_keys)
        tools_menu.add_separator()
        tools_menu.add_command(label="Check for Updates", command=self._check_updates)
        tools_menu.add_command(label="Update FOL", command=self._update_fol)
        tools_menu.add_separator()
        tools_menu.add_command(label="Install System Dependencies", command=self._install_system_deps)
        tools_menu.add_command(label="Install Python Dependencies", command=self._install_deps)
        tools_menu.add_separator()
        tools_menu.add_command(label="Verify Installation", command=self._verify_installation)
        tools_menu.add_separator()
        tools_menu.add_command(label="Start System Tray Icon", command=self._start_tray)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Documentation", command=self._open_docs)
        help_menu.add_command(label="GitHub", command=self._open_github)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _create_main_layout(self):
        """Create the main window layout."""
        # Main container
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        ttk.Label(main, text="🧠 FOL Control Panel", style="Title.TLabel").pack(pady=(0, 10))

        # Theme toggle button (top right)
        theme_frame = ttk.Frame(main)
        theme_frame.pack(fill=tk.X)
        theme_btn = ttk.Button(theme_frame, text="🌙 Dark / ☀️ Light", command=self._toggle_theme)
        theme_btn.pack(side=tk.RIGHT)

        # Create notebook (tabs)
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Services
        self._create_services_tab()

        # Tab 2: API Keys
        self._create_api_keys_tab()

        # Tab 3: Settings
        self._create_settings_tab()

        # Tab 4: Logs
        self._create_logs_tab()

        # Status bar
        self._create_status_bar(main)

    # ----- Tab 1: Services -----

    def _create_services_tab(self):
        """Create the services control tab."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  ⚡ Services  ")

        # Services frame
        services_frame = ttk.LabelFrame(tab, text="Running Services", padding=10)
        services_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.service_widgets: dict[str, dict[str, Any]] = {}

        for svc_id, svc in SERVICES.items():
            row = ttk.Frame(services_frame)
            row.pack(fill=tk.X, pady=3)

            # Status indicator
            indicator = ttk.Label(row, text="●", font=("Helvetica", 14))
            indicator.pack(side=tk.LEFT, padx=(0, 10))

            # Service name + port
            info = ttk.Label(row, text=f"{svc['name']}  (port {svc['port']})", style="Status.TLabel")
            info.pack(side=tk.LEFT, padx=(0, 10))

            # Start button
            start_btn = ttk.Button(row, text="▶ Start", style="Start.TButton",
                                   command=lambda s=svc_id: self._start_service(s))
            start_btn.pack(side=tk.RIGHT, padx=2)

            # Stop button
            stop_btn = ttk.Button(row, text="■ Stop", style="Stop.TButton",
                                  command=lambda s=svc_id: self._stop_service(s))
            stop_btn.pack(side=tk.RIGHT, padx=2)

            self.service_widgets[svc_id] = {
                "indicator": indicator,
                "info": info,
                "start_btn": start_btn,
                "stop_btn": stop_btn,
            }

        # Action buttons
        actions = ttk.Frame(tab)
        actions.pack(fill=tk.X)

        ttk.Button(actions, text="▶ Start All", style="Start.TButton",
                   command=self._start_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(actions, text="■ Stop All", style="Stop.TButton",
                   command=self._stop_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(actions, text="🔄 Refresh Status",
                   command=self._check_status).pack(side=tk.RIGHT, padx=5)

    # ----- Tab 2: API Keys -----

    def _create_api_keys_tab(self):
        """Create the API keys configuration tab."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  🔑 API Keys  ")

        # Scrollable frame
        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Header
        ttk.Label(scrollable, text="Configure API Keys", style="Header.TLabel").pack(pady=(0, 10))
        ttk.Label(scrollable, text="Enter your keys below. Click 'Validate' to check each one.",
                  font=("Helvetica", 9)).pack(pady=(0, 10))

        self.key_entries: dict[str, ttk.Entry] = {}
        self.key_status: dict[str, ttk.Label] = {}

        for env_var, display_name in PROVIDERS.items():
            row = ttk.Frame(scrollable)
            row.pack(fill=tk.X, pady=3)

            # Label
            ttk.Label(row, text=f"{display_name}:", width=25, anchor="w").pack(side=tk.LEFT)

            # Entry (show * for secrets)
            entry = ttk.Entry(row, width=50, show="*")
            entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

            # Load existing value
            current = self.env.get(env_var, "")
            if current:
                entry.insert(0, current)

            # Status label
            status = ttk.Label(row, text="⬜", width=5)
            status.pack(side=tk.LEFT, padx=5)

            self.key_entries[env_var] = entry
            self.key_status[env_var] = status

        # Buttons
        btn_frame = ttk.Frame(scrollable)
        btn_frame.pack(fill=tk.X, pady=10)

        ttk.Button(btn_frame, text="💾 Save Keys", command=self._save_keys).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="✅ Validate All", command=self._validate_all_keys).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🔄 Reload", command=self._reload_keys).pack(side=tk.LEFT, padx=5)

        # Scrollbar
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # ----- Tab 3: Settings -----

    def _create_settings_tab(self):
        """Create the settings tab."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  ⚙️ Settings  ")

        # Brain backend
        brain_frame = ttk.LabelFrame(tab, text="🧠 Brain Backend", padding=10)
        brain_frame.pack(fill=tk.X, pady=(0, 10))

        self.brain_var = tk.StringVar(value=self.env.get("FOL_BRAIN", "current"))
        for value, label in BRAIN_OPTIONS.items():
            ttk.Radiobutton(brain_frame, text=label, variable=self.brain_var,
                           value=value).pack(anchor="w", pady=2)

        # STT provider
        stt_frame = ttk.LabelFrame(tab, text="🎤 Speech-to-Text (STT)", padding=10)
        stt_frame.pack(fill=tk.X, pady=(0, 10))

        self.stt_var = tk.StringVar(value=self.env.get("FOL_STT_PROVIDER", "mlx_whisper"))
        for value, label in STT_OPTIONS.items():
            ttk.Radiobutton(stt_frame, text=label, variable=self.stt_var,
                           value=value).pack(anchor="w", pady=2)

        # LLM Model
        model_frame = ttk.LabelFrame(tab, text="🤖 LLM Model", padding=10)
        model_frame.pack(fill=tk.X, pady=(0, 10))

        model_row = ttk.Frame(model_frame)
        model_row.pack(fill=tk.X)
        ttk.Label(model_row, text="Primary model:").pack(side=tk.LEFT)
        self.model_entry = ttk.Entry(model_row, width=60)
        self.model_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.model_entry.insert(0, self.env.get("LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash:free"))

        # Save button
        ttk.Button(tab, text="💾 Save Settings", command=self._save_settings).pack(pady=10)

    # ----- Tab 4: Logs -----

    def _create_logs_tab(self):
        """Create the log viewer tab."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  📋 Logs  ")

        # Log display
        self.log_text = scrolledtext.ScrolledText(tab, height=20, font=("Courier", 10),
                                                   wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Buttons
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="🔄 Refresh", command=self._refresh_logs).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="🗑 Clear", command=self._clear_logs).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="📂 Open Logs Folder", command=self._open_logs_folder).pack(side=tk.RIGHT, padx=5)

    # ----- Status Bar -----

    def _create_status_bar(self, parent):
        """Create the bottom status bar."""
        self.status_bar = ttk.Frame(parent)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_label = ttk.Label(self.status_bar, text="Ready", style="Status.TLabel")
        self.status_label.pack(side=tk.LEFT, padx=5)

        self.platform_label = ttk.Label(self.status_bar,
            text=f"Platform: {sys.platform}", style="Status.TLabel")
        self.platform_label.pack(side=tk.RIGHT, padx=5)

    # ----- Service Management -----

    def _start_service(self, svc_id: str):
        """Start a service in the background."""
        svc = SERVICES[svc_id]
        cmd = svc["cmd"]
        if cmd[0] == "python3":
            cmd[0] = get_python()

        try:
            log_path = os.path.join(_PROJECT_ROOT, "logs", f"{svc_id}.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            log_file = open(log_path, "a")

            proc = subprocess.Popen(
                cmd,
                cwd=_PROJECT_ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self.processes[svc_id] = proc
            self._log(f"✅ Started {svc['name']} (PID: {proc.pid})")
            self._check_status()
        except Exception as exc:
            self._log(f"❌ Failed to start {svc['name']}: {exc}")
            messagebox.showerror("Error", f"Failed to start {svc['name']}:\n{exc}")

    def _stop_service(self, svc_id: str):
        """Stop a running service."""
        proc = self.processes.get(svc_id)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            self._log(f"⏹ Stopped {SERVICES[svc_id]['name']}")
        elif is_port_open(SERVICES[svc_id]["port"]):
            import socket
            self._log(f"⚠️ Service on port {SERVICES[svc_id]['port']} was started externally")
        self._check_status()

    def _start_all(self):
        """Start all services."""
        for svc_id in SERVICES:
            if not is_port_open(SERVICES[svc_id]["port"]):
                self._start_service(svc_id)
                time.sleep(1)

    def _stop_all(self):
        """Stop all services."""
        for svc_id in list(self.processes.keys()):
            self._stop_service(svc_id)

    def _check_status(self):
        """Check and update service status indicators."""
        t = THEMES[self._current_theme]
        for svc_id, svc in SERVICES.items():
            widget = self.service_widgets[svc_id]
            running = is_port_open(svc["port"])

            if running:
                widget["indicator"].configure(text="●", foreground=t["green"])
            else:
                widget["indicator"].configure(text="●", foreground=t["red"])

        # Update status bar
        running_count = sum(1 for s in SERVICES.values() if is_port_open(s["port"]))
        self.status_label.configure(text=f"Services: {running_count}/{len(SERVICES)} running")

        # Schedule next check
        if self._running:
            self.after(3000, self._check_status)

    # ----- API Key Management -----

    def _save_keys(self):
        """Save all API keys to .env."""
        updates = {}
        for env_var, entry in self.key_entries.items():
            val = entry.get().strip()
            if val:
                updates[env_var] = val

        if updates:
            save_env(updates)
            self.env.update(updates)
            self._log(f"💾 Saved {len(updates)} API key(s)")
            messagebox.showinfo("Saved", f"Saved {len(updates)} API key(s) to .env")
        else:
            messagebox.showinfo("Nothing to save", "No keys entered.")

    def _validate_all_keys(self):
        """Validate all entered API keys."""
        self._log("🔑 Validating API keys...")
        for env_var, entry in self.key_entries.items():
            key = entry.get().strip()
            status = self.key_status[env_var]
            if not key:
                status.configure(text="⬜")
                continue

            threading.Thread(target=self._validate_single_key,
                           args=(env_var, key, status), daemon=True).start()

    def _validate_single_key(self, env_var: str, key: str, status_label: ttk.Label):
        """Validate a single API key in a background thread."""
        try:
            old_val = os.environ.get(env_var)
            os.environ[env_var] = key

            from modules.llm.key_manager import KeyManager
            km = KeyManager()
            provider = env_var.replace("_API_KEY", "").lower()

            result = km.validate(provider, key)

            if old_val is not None:
                os.environ[env_var] = old_val
            elif env_var in os.environ:
                del os.environ[env_var]

            self.after(0, lambda: self._update_key_status(status_label, result.ok, result.message))

        except Exception as exc:
            self.after(0, lambda: self._update_key_status(status_label, False, str(exc)[:50]))

    def _update_key_status(self, label: ttk.Label, ok: bool, message: str):
        """Update a key status label."""
        t = THEMES[self._current_theme]
        if ok:
            label.configure(text="✅", foreground=t["green"])
        else:
            label.configure(text="❌", foreground=t["red"])
        label.tooltip = message

    def _reload_keys(self):
        """Reload keys from .env."""
        self.env = load_env()
        for env_var, entry in self.key_entries.items():
            entry.delete(0, tk.END)
            entry.insert(0, self.env.get(env_var, ""))
        self._log("🔄 Reloaded keys from .env")

    # ----- Settings -----

    def _save_settings(self):
        """Save brain/STT/model settings."""
        updates = {
            "FOL_BRAIN": self.brain_var.get(),
            "FOL_STT_PROVIDER": self.stt_var.get(),
            "LLM_MODEL": self.model_entry.get().strip(),
        }
        save_env(updates)
        self.env.update(updates)
        self._log(f"💾 Saved settings: brain={updates['FOL_BRAIN']}, stt={updates['FOL_STT_PROVIDER']}")
        messagebox.showinfo("Saved", "Settings saved to .env")

    # ----- Logs -----

    def _log(self, message: str):
        """Append a message to the log viewer."""
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _refresh_logs(self):
        """Refresh log display from log files."""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)

        logs_dir = os.path.join(_PROJECT_ROOT, "logs")
        if os.path.isdir(logs_dir):
            for fname in sorted(os.listdir(logs_dir))[-5:]:
                fpath = os.path.join(logs_dir, fname)
                if os.path.isfile(fpath):
                    self.log_text.insert(tk.END, f"=== {fname} ===\n")
                    try:
                        with open(fpath) as f:
                            lines = f.readlines()[-50:]
                        for line in lines:
                            self.log_text.insert(tk.END, line)
                    except Exception:
                        self.log_text.insert(tk.END, "(could not read)\n")
                    self.log_text.insert(tk.END, "\n")

        self.log_text.configure(state=tk.DISABLED)
        self._log("🔄 Logs refreshed")

    def _clear_logs(self):
        """Clear the log display."""
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _open_logs_folder(self):
        """Open the logs folder in the file manager."""
        logs_dir = os.path.join(_PROJECT_ROOT, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        if sys.platform == "darwin":
            subprocess.Popen(["open", logs_dir])
        elif sys.platform == "win32":
            os.startfile(logs_dir)
        else:
            subprocess.Popen(["xdg-open", logs_dir])

    # ----- Menu actions -----

    def _open_env_file(self):
        """Open .env in default editor."""
        env_path = os.path.join(_PROJECT_ROOT, ".env")
        if not os.path.isfile(env_path):
            env_path = os.path.join(_PROJECT_ROOT, ".env.template")
        if sys.platform == "darwin":
            subprocess.Popen(["open", env_path])
        elif sys.platform == "win32":
            os.startfile(env_path)
        else:
            subprocess.Popen(["xdg-open", env_path])

    def _open_project_folder(self):
        """Open project root in file manager."""
        if sys.platform == "darwin":
            subprocess.Popen(["open", _PROJECT_ROOT])
        elif sys.platform == "win32":
            os.startfile(_PROJECT_ROOT)
        else:
            subprocess.Popen(["xdg-open", _PROJECT_ROOT])

    def _run_setup_wizard(self):
        """Run the setup wizard in a new terminal."""
        wizard = os.path.join(_PROJECT_ROOT, "setup", "setup_wizard.py")
        if sys.platform == "win32":
            subprocess.Popen(["start", "cmd", "/k", get_python(), wizard], shell=True)
        else:
            subprocess.Popen(["python3", wizard])

    def _validate_keys(self):
        """Run the key validator in a new terminal."""
        validator = os.path.join(_PROJECT_ROOT, "setup", "validate_keys.py")
        if sys.platform == "win32":
            subprocess.Popen(["start", "cmd", "/k", get_python(), validator], shell=True)
        else:
            subprocess.Popen(["python3", validator])

    def _install_deps(self):
        """Install Python dependencies."""
        req_file = "requirements.txt"
        if sys.platform == "win32":
            req_file = "requirements-windows.txt"
        elif sys.platform == "linux":
            req_file = "requirements-linux.txt"

        req_path = os.path.join(_PROJECT_ROOT, req_file)
        if not os.path.isfile(req_path):
            req_path = os.path.join(_PROJECT_ROOT, "requirements.txt")

        self._log(f"📦 Installing Python dependencies from {req_file}...")
        threading.Thread(target=self._do_install_deps, args=(req_path,), daemon=True).start()

    def _install_system_deps(self):
        """Install system dependencies (apt/dnf/brew/choco)."""
        self._log("📦 Installing system dependencies...")
        installer = os.path.join(_PROJECT_ROOT, "setup", "install_deps.py")
        if sys.platform == "win32":
            subprocess.Popen(["start", "cmd", "/k", get_python(), installer], shell=True)
        else:
            threading.Thread(target=self._do_install_system_deps, daemon=True).start()

    def _do_install_system_deps(self):
        """Install system dependencies in background."""
        installer = os.path.join(_PROJECT_ROOT, "setup", "install_deps.py")
        try:
            result = subprocess.run(
                [get_python(), installer],
                capture_output=True, text=True, cwd=_PROJECT_ROOT,
            )
            for line in result.stdout.splitlines()[-10:]:
                self.after(0, lambda l=line: self._log(l))
            if result.returncode == 0:
                self.after(0, lambda: self._log("✅ System dependencies installed"))
            else:
                self.after(0, lambda: self._log("⚠️ Some dependencies may have failed"))
        except Exception as exc:
            self.after(0, lambda: self._log(f"❌ Install error: {exc}"))

    def _verify_installation(self):
        """Verify all tools are installed."""
        self._log("🔍 Verifying installation...")
        threading.Thread(target=self._do_verify, daemon=True).start()

    def _do_verify(self):
        """Verify installation in background."""
        installer = os.path.join(_PROJECT_ROOT, "setup", "install_deps.py")
        try:
            result = subprocess.run(
                [get_python(), installer, "--verify"],
                capture_output=True, text=True, cwd=_PROJECT_ROOT,
            )
            for line in result.stdout.splitlines():
                self.after(0, lambda l=line: self._log(l))
        except Exception as exc:
            self.after(0, lambda: self._log(f"❌ Verify error: {exc}"))

    def _do_install_deps(self, req_path: str):
        """Install dependencies in background."""
        try:
            result = subprocess.run(
                [get_python(), "-m", "pip", "install", "-r", req_path, "--quiet"],
                capture_output=True, text=True, cwd=_PROJECT_ROOT,
            )
            if result.returncode == 0:
                self.after(0, lambda: self._log("✅ Dependencies installed successfully"))
            else:
                self.after(0, lambda: self._log(f"⚠️ Install warnings: {result.stderr[:200]}"))
        except Exception as exc:
            self.after(0, lambda: self._log(f"❌ Install failed: {exc}"))

    # ----- Update Management -----

    def _background_update_check(self):
        """Check for updates in background on startup."""
        threading.Thread(target=self._do_background_update_check, daemon=True).start()

    def _do_background_update_check(self):
        """Background update check."""
        try:
            updater_path = os.path.join(_PROJECT_ROOT, "setup", "auto_update.py")
            result = subprocess.run(
                [get_python(), updater_path, "--check"],
                capture_output=True, text=True, cwd=_PROJECT_ROOT, timeout=30,
            )
            # Parse output for updates available
            output = result.stdout
            if "Pending updates" in output or "commit(s))" in output:
                self.after(0, lambda: self._show_update_notification(output))
        except Exception:
            pass  # Silently ignore — not critical

    def _show_update_notification(self, details: str):
        """Show a notification that updates are available."""
        t = THEMES[self._current_theme]
        self._log("🔄 Updates available from GitHub!")
        # Update status bar
        self.status_label.configure(
            text="🔄 Updates available — Tools → Update FOL",
            foreground=t["yellow"]
        )

    def _check_updates(self):
        """Check for updates (interactive)."""
        self._log("🔍 Checking for updates...")
        threading.Thread(target=self._do_check_updates, daemon=True).start()

    def _do_check_updates(self):
        """Check for updates in background."""
        try:
            updater_path = os.path.join(_PROJECT_ROOT, "setup", "auto_update.py")
            result = subprocess.run(
                [get_python(), updater_path, "--check"],
                capture_output=True, text=True, cwd=_PROJECT_ROOT, timeout=30,
            )
            for line in result.stdout.splitlines():
                self.after(0, lambda l=line: self._log(l))
            if "Up to date" in result.stdout:
                self.after(0, lambda: self._log("✅ FOL is up to date"))
            elif "Pending updates" in result.stdout:
                self.after(0, lambda: self._log("📥 Updates available — use 'Update FOL' to install"))
            elif "Not a git" in result.stdout:
                self.after(0, lambda: self._log("⚠️ Not a git repository — cannot check updates"))
        except Exception as exc:
            self.after(0, lambda: self._log(f"❌ Update check failed: {exc}"))

    def _update_fol(self):
        """Update FOL from GitHub (interactive)."""
        if not messagebox.askyesno("Update FOL",
            "This will pull the latest changes from GitHub.\n\n"
            "Uncommitted changes will be stashed.\n"
            "A backup tag will be created.\n\n"
            "Continue?"):
            return

        self._log("🔄 Updating FOL from GitHub...")
        threading.Thread(target=self._do_update_fol, daemon=True).start()

    def _do_update_fol(self):
        """Perform the update in background."""
        try:
            updater_path = os.path.join(_PROJECT_ROOT, "setup", "auto_update.py")
            result = subprocess.run(
                [get_python(), updater_path, "--force"],
                input="y\n",
                capture_output=True, text=True, cwd=_PROJECT_ROOT, timeout=300,
            )
            for line in result.stdout.splitlines():
                self.after(0, lambda l=line: self._log(l))
            if result.returncode == 0:
                self.after(0, lambda: self._log("✅ Update complete! Restart recommended."))
                self.after(0, lambda: messagebox.showinfo("Update Complete",
                    "FOL has been updated successfully!\n\n"
                    "Restart the launcher to apply changes."))
            else:
                self.after(0, lambda: self._log("⚠️ Update may have failed — check logs"))
        except Exception as exc:
            self.after(0, lambda: self._log(f"❌ Update failed: {exc}"))

    def _start_tray(self):
        """Start the system tray icon in background."""
        tray_script = os.path.join(_PROJECT_ROOT, "setup", "system_tray.py")
        try:
            if sys.platform == "win32":
                subprocess.Popen(["start", "cmd", "/k", get_python(), tray_script], shell=True)
            else:
                subprocess.Popen([get_python(), tray_script],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._log("🖥 System tray icon started")
        except Exception as exc:
            self._log(f"❌ Failed to start tray: {exc}")

    def _open_docs(self):
        """Open documentation."""
        import webbrowser
        webbrowser.open("https://github.com/abdulakimabdimanapov-rgb/SecondSelf")

    def _open_github(self):
        """Open GitHub repo."""
        import webbrowser
        webbrowser.open("https://github.com/abdulakimabdimanapov-rgb/SecondSelf")

    # ----- Cleanup -----

    def _on_close(self):
        """Clean up on window close."""
        self._running = False
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Launch the FOL GUI."""
    app = FOLLauncher()
    app.mainloop()


if __name__ == "__main__":
    main()
