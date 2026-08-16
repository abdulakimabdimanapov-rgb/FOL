# Phase 3 — Screen Context Detection + Proactive Suggestions

> **Статус:** Спецификация
> **Цель:** FOL понимает, что происходит на экране пользователя, и предлагает релевантные действия
> **Компоненты:** `context_engine/`, улучшенный `suggestion_engine.py`, новые инструменты для LLM

---

## 1. АНАЛИЗ ТЕКУЩЕЙ СИСТЕМЫ

### 1.1 Suggestion Engine (`orchestrator/suggestion_engine.py`)

**Текущие 3 триггера:**

| Триггер | Вызов | Частота | Входные данные |
|---------|-------|---------|----------------|
| `profile_trigger` | После профилирования | 1 раз | Tavily profile |
| `pattern_trigger` | После каждого job | После каждого ответа | Conversation history |
| `ambient_tick` | Ambient loop | Каждые 30s | Скриншот + conversation history + rewards |

**Проблемы текущей системы:**
1. **Нет контекста активного приложения** — не знает, в каком приложении пользователь
2. **Скриншот дорогой** — каждые 30s скриншот десктопа ~100ms + LLM вызов
3. **Нет URL из браузера** — не может предложить действия на основе открытой страницы
4. **Нет истории контекста** — не помнит, что было открыто 5 минут назад
5. **LLM вызывается каждый тик** — дорого, даже когда нечего предлагать
6. **Нет анализа проекта** — не знает, какой проект в VS Code открыт

### 1.2 Ambient Loop (`orchestrator/server.py`)

```python
async def _ambient_loop():
    while True:
        await asyncio.sleep(ambient_interval)  # 30s
        if current_job["state"] in ("thinking", "working"):
            continue  # Пропускаем, если занят
        suggestions = await asyncio.to_thread(
            ambient_tick, list(_conversation_history), cached_profile
        )
        for suggestion in suggestions:
            await broadcast_event("suggestion", suggestion)
```

**Проблемы:**
1. **Слепой интервал** — всегда 30s, не адаптируется под активность пользователя
2. **Нет приоритетов** — все предложения равны
3. **Нет подавления шума** — если пользователь постоянно отклоняет, всё равно предлагает
4. **Нет контекстных окон** — предлагает даже когда пользователь в фулскрин-игре

---

## 2. НОВАЯ АРХИТЕКТУРА

```
┌─────────────────────────────────────────────────────────┐
│                  Context Engine (новый)                  │
│                                                         │
│  ┌──────────────────────┐   ┌──────────────────────┐   │
│  │  App Monitor          │   │  Window Analyzer     │   │
│  │  (NSWorkspace)        │   │  (Accessibility API) │   │
│  │  ─ Активное приложение│   │  ─ Заголовок окна    │   │
│  │  ─ Bundle ID          │   │  ─ Размер/позиция    │   │
│  │  ─ PID                │   │  ─ Режим (фулскрин) │   │
│  └──────────┬───────────┘   └──────────┬───────────┘   │
│             │                          │               │
│  ┌──────────┴───────────┐   ┌──────────┴───────────┐   │
│  │  Browser URL Parser   │   │  Project Detector    │   │
│  │  (AppleScript)        │   │  (VS Code, Terminal) │   │
│  │  ─ Chrome URL         │   │  ─ Git info          │   │
│  │  ─ Safari URL         │   │  ─ Working directory │   │
│  │  ─ Arc URL            │   │  ─ Open files        │   │
│  └──────────┬───────────┘   └──────────┬───────────┘   │
│             │                          │               │
│  ┌──────────┴──────────────────────────┴───────────┐   │
│  │  Context Snapshot                                 │   │
│  │  { app, url, project, window, timestamp }        │   │
│  └──────────────────────┬──────────────────────────┘   │
└─────────────────────────┼─────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│            Улучшенный Suggestion Engine                  │
│                                                         │
│  ┌────────────┐ ┌────────────┐ ┌────────────────────┐  │
│  │ Profile    │ │ Pattern    │ │ Context-aware      │  │
│  │ Trigger    │ │ Trigger    │ │ Trigger (NEW)      │  │
│  └────────────┘ └────────────┘ └─────────┬──────────┘  │
│                                          │             │
│  ┌──────────────────────────────────────────┐          │
│  │  Suggestion Router                        │          │
│  │  ─ Context history                       │          │
│  │  ─ Reward learning                       │          │
│  │  ─ Adaptive interval                     │          │
│  │  ─ Deduplication                         │          │
│  └──────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

---

## 3. CONTEXT ENGINE

### 3.1 Файловая структура

```
context_engine/
├── __init__.py
├── app_monitor.py          # NSWorkspace — активное приложение
├── window_analyzer.py      # Accessibility API — заголовки окон
├── browser_url.py          # AppleScript — URL из браузеров
├── project_detector.py     # VS Code, Terminal, Git
├── snapshot.py             # Context Snapshot (объединяет всё)
├── history.py              # История контекста (кольцевой буфер)
├── config.py               # Настройки
└── server_endpoints.py     # HTTP endpoints для orchestrator
```

### 3.2 `app_monitor.py` — определение активного приложения

```python
"""App Monitor — macOS NSWorkspace-based active application detection.

Использует NSWorkspace для получения фронтмаст-приложения.
Не требует Accessibility permission.
Работает через PyObjC мост из Python.
"""

import logging
import subprocess
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def get_active_app() -> dict[str, Any]:
    """Get the currently active (frontmost) application.
    
    Uses AppleScript for process info retrieval (works from Python).
    No PyObjC dependency needed.
    
    Returns:
        {
            "name": "Google Chrome",
            "bundle_id": "com.google.Chrome",
            "pid": 12345,
            "timestamp": "2026-04-12T14:30:00Z"
        }
    """
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        set bundleId to bundle identifier of frontApp
        set pid to unix id of frontApp
        return appName & "|||" & bundleId & "|||" & pid
    end tell
    """
    
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            logger.warning("Failed to get active app: %s", result.stderr)
            return {"name": "unknown", "bundle_id": "", "pid": 0}
        
        parts = result.stdout.strip().split("|||")
        return {
            "name": parts[0] if len(parts) > 0 else "unknown",
            "bundle_id": parts[1] if len(parts) > 1 else "",
            "pid": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    except subprocess.TimeoutExpired:
        logger.warning("Active app detection timed out")
        return {"name": "unknown", "bundle_id": "", "pid": 0}
    except Exception as exc:
        logger.warning("Active app detection failed: %s", exc)
        return {"name": "unknown", "bundle_id": "", "pid": 0}


# Cache: последний известный активный app (для сравнения изменений)
_last_active_app: dict[str, Any] = {}


def has_app_changed() -> bool:
    """Check if the active app has changed since last call.
    
    Returns True if changed, also updates the cache.
    """
    global _last_active_app
    current = get_active_app()
    if current["name"] != _last_active_app.get("name"):
        _last_active_app = current
        return True
    return False


def get_app_category(bundle_id: str) -> str:
    """Categorize an application by its bundle ID."""
    CATEGORIES = {
        # Browsers
        "com.google.Chrome": "browser",
        "com.apple.Safari": "browser",
        "company.thebrowser.Browser": "browser",  # Arc
        "com.microsoft.edgemac": "browser",
        "org.mozilla.firefox": "browser",
        # IDE
        "com.microsoft.VSCode": "ide",
        "com.jetbrains.intellij": "ide",
        "com.apple.dt.Xcode": "ide",
        # Terminal
        "com.apple.Terminal": "terminal",
        "com.googlecode.iterm2": "terminal",
        "co.zeit.hyper": "terminal",
        "com.apple.dt.Xcode": "ide",
        # Communication
        "com.tinyspeck.slackmacgap": "communication",
        "com.microsoft.teams2": "communication",
        "com.getzoom.Zoom": "communication",
        "com.discord": "communication",
        # Productivity
        "md.obsidian": "notes",
        "com.apple.Notes": "notes",
        "com.apple.iCal": "calendar",
        "com.apple.mail": "email",
        "com.google.Chrome.canary": "browser",
        # Media
        "com.apple.TV": "media",
        "com.spotify.client": "media",
        "com.apple.QuickTimePlayerX": "media",
        "com.google.YouTube": "media",
        # Design
        "com.figma.Desktop": "design",
        "com.adobe.Photoshop": "design",
        "com.skitch.cloud": "design",
    }
    return CATEGORIES.get(bundle_id, "other")
```

### 3.3 `window_analyzer.py` — анализ окон

```python
"""Window Analyzer — macOS Accessibility API based window detection.

Требует Accessibility permissions.
Использует AppleScript для получения информации об окнах.
"""

import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def get_focused_window() -> dict[str, Any]:
    """Get the focused window's title and position.
    
    Uses AppleScript's System Events for window info.
    
    Returns:
        {
            "title": "index.tsx — VS Code",
            "x": 0, "y": 0, "width": 1440, "height": 900,
            "is_fullscreen": False,
        }
    """
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        
        if exists (first window of frontApp) then
            set win to first window of frontApp
            set winTitle to title of win
            set winX to position x of win
            set winY to position y of win
            set winW to width of win
            set winH to height of win
            
            -- Check if fullscreen (rough: window matches screen)
            set screenRes to bounds of first item of (get bounds of window of desktop)
            
            return winTitle & "|||" & winX & "|||" & winY & "|||" & winW & "|||" & winH
        else
            return ""
        end if
    end tell
    """
    
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {"title": "", "x": 0, "y": 0, "width": 0, "height": 0, "is_fullscreen": False}
        
        parts = result.stdout.strip().split("|||")
        return {
            "title": parts[0] if len(parts) > 0 else "",
            "x": int(parts[1]) if len(parts) > 1 else 0,
            "y": int(parts[2]) if len(parts) > 2 else 0,
            "width": int(parts[3]) if len(parts) > 3 else 0,
            "height": int(parts[4]) if len(parts) > 4 else 0,
            "is_fullscreen": False,  # Определяется через сравнение с размером экрана
        }
    except Exception as exc:
        logger.debug("Window analysis failed: %s", exc)
        return {"title": "", "x": 0, "y": 0, "width": 0, "height": 0, "is_fullscreen": False}
```

### 3.4 `browser_url.py` — получение URL из браузера

```python
"""Browser URL Parser — AppleScript-based URL extraction.

Поддерживает: Chrome, Safari, Arc, Edge, Firefox.
Не требует Accessibility API.
"""

import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# AppleScript for each browser
BROWSER_SCRIPTS = {
    "Google Chrome": """
        tell application "Google Chrome"
            if (count of windows) > 0 then
                set win to front window
                set activeTab to active tab of win
                return (URL of activeTab) & "|||" & (title of activeTab)
            end if
        end tell
    """,
    "Safari": """
        tell application "Safari"
            if (count of windows) > 0 then
                set win to front window
                set currentTab to current tab of win
                return (URL of currentTab) & "|||" & (name of currentTab)
            end if
        end tell
    """,
    "Arc": """
        tell application "Arc"
            if (count of windows) > 0 then
                set win to front window
                set activeTab to active tab of win
                return (URL of activeTab) & "|||" & (title of activeTab)
            end if
        end tell
    """,
    "Microsoft Edge": """
        tell application "Microsoft Edge"
            if (count of windows) > 0 then
                set win to front window
                set activeTab to active tab of win
                return (URL of activeTab) & "|||" & (title of activeTab)
            end if
        end tell
    """,
    "Firefox": """
        tell application "Firefox"
            -- Firefox AppleScript support is limited
            -- Fallback: use Accessibility API via System Events
            tell application "System Events"
                tell process "Firefox"
                    set urlBar to text field 1 of toolbar 1 of window 1
                    return (value of urlBar)
                end tell
            end tell
        end tell
    """,
}


def get_browser_url(app_name: str) -> dict[str, Any]:
    """Get the URL and page title from the specified browser.
    
    Args:
        app_name: "Google Chrome" | "Safari" | "Arc" | etc.
    
    Returns:
        {
            "url": "https://github.com/...",
            "title": "My Repo — GitHub",
            "domain": "github.com",
        }
        or {"url": "", "title": ""} if not available.
    """
    script = BROWSER_SCRIPTS.get(app_name)
    if not script:
        return {"url": "", "title": "", "domain": ""}
    
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {"url": "", "title": "", "domain": ""}
        
        parts = result.stdout.strip().split("|||")
        url = parts[0] if len(parts) > 0 else ""
        
        # Extract domain from URL
        domain = ""
        if url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.netloc or parsed.hostname or ""
            except Exception:
                domain = ""
        
        return {
            "url": url,
            "title": parts[1] if len(parts) > 1 else "",
            "domain": domain,
        }
    except subprocess.TimeoutExpired:
        logger.debug("Browser URL detection timed out for %s", app_name)
        return {"url": "", "title": "", "domain": ""}
    except Exception as exc:
        logger.debug("Browser URL detection failed for %s: %s", app_name, exc)
        return {"url": "", "title": "", "domain": ""}


def classify_url(domain: str) -> str:
    """Classify a URL domain into a category."""
    CATEGORIES = {
        # Development
        "github.com": "development",
        "gitlab.com": "development",
        "bitbucket.org": "development",
        "stackoverflow.com": "development",
        "developer.apple.com": "development",
        # Productivity
        "mail.google.com": "email",
        "calendar.google.com": "calendar",
        "docs.google.com": "documents",
        "drive.google.com": "storage",
        "notion.so": "notes",
        "linear.app": "project_management",
        "asana.com": "project_management",
        "trello.com": "project_management",
        # Media
        "youtube.com": "media",
        "netflix.com": "media",
        "spotify.com": "media",
        # Social
        "twitter.com": "social",
        "x.com": "social",
        "reddit.com": "social",
        "linkedin.com": "social",
        "discord.com": "social",
        "slack.com": "communication",
    }
    
    for key, category in CATEGORIES.items():
        if key in domain:
            return category
    return "browsing"
```

### 3.5 `project_detector.py` — определение проекта

```python
"""Project Detector — определяет текущий проект из IDE или Terminal.

Поддерживает: VS Code, Terminal, iTerm2, Xcode.
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# VS Code window titles typically: "path/to/project — VS Code" or "file.ts — project — VS Code"
VS_CODE_PATTERN = re.compile(r"^(?:.* — )?(.+?) — VS Code$")
VS_CODE_INSIDERS_PATTERN = re.compile(r"^(?:.* — )?(.+?) — VS Code Insiders$")


def detect_vscode_project(window_title: str) -> dict[str, Any]:
    """Extract project info from VS Code window title.
    
    Args:
        window_title: e.g. "app/page.tsx — FOL — VS Code"
    
    Returns:
        {"project": "FOL", "path": "/Users/.../FOL", "file": "app/page.tsx"}
        or {"project": ""} if not detected.
    """
    match = VS_CODE_PATTERN.match(window_title)
    if not match:
        match = VS_CODE_INSIDERS_PATTERN.match(window_title)
    if not match:
        return {"project": "", "path": "", "file": ""}
    
    title_content = match.group(1)  # "app/page.tsx — FOL"
    
    # Check for file separator
    parts = title_content.split(" — ")
    if len(parts) >= 2:
        file_part = parts[0].strip()
        project_name = parts[-1].strip()
        
        # Try to find the project path
        project_path = _find_project_path(project_name)
        
        return {
            "project": project_name,
            "path": str(project_path) if project_path else "",
            "file": file_part,
        }
    
    return {"project": title_content, "path": "", "file": ""}


def detect_terminal_project(window_title: str) -> dict[str, Any]:
    """Try to detect current project from terminal window title.
    
    Terminal emulators often set the window title to the current directory
    or "command — directory".
    """
    # iTerm2 often shows: "user@host: ~/project"
    # Terminal.app often shows: "project — bash — 80×24"
    
    # Check if window title looks like a path
    if "~" in window_title or window_title.startswith("/"):
        # Extract path-like segments
        path_part = window_title.split(" — ")[0].strip()
        expanded = os.path.expanduser(path_part)
        if os.path.isdir(expanded):
            folder_name = Path(expanded).name
            return {
                "project": folder_name,
                "path": expanded,
                "file": "",
            }
    
    # Default: just use the window title
    return {"project": window_title, "path": "", "file": ""}


def _find_project_path(project_name: str) -> Path | None:
    """Find a project directory by name in common locations."""
    common_roots = [
        Path.home() / "Desktop",
        Path.home() / "Projects",
        Path.home() / "Developer",
        Path.home(),
    ]
    
    for root in common_roots:
        if not root.exists():
            continue
        for item in root.iterdir():
            if item.is_dir() and item.name == project_name:
                # Verify it has .git or package.json
                if (item / ".git").exists() or (item / "package.json").exists() \
                   or (item / "Cargo.toml").exists() or (item / "requirements.txt").exists():
                    return item
    return None
```

### 3.6 `snapshot.py` — Context Snapshot

```python
"""Context Snapshot — объединяет всё в один объект состояния.

Главный API для orchestrator: context_engine.get_snapshot()
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from context_engine.app_monitor import get_active_app, get_app_category
from context_engine.window_analyzer import get_focused_window
from context_engine.browser_url import get_browser_url, classify_url
from context_engine.project_detector import detect_vscode_project, detect_terminal_project

logger = logging.getLogger(__name__)


@dataclass
class ContextSnapshot:
    """Полный снимок контекста пользователя."""
    
    # Active application
    app_name: str = ""
    app_bundle_id: str = ""
    app_pid: int = 0
    app_category: str = "other"
    
    # Window
    window_title: str = ""
    is_fullscreen: bool = False
    
    # Browser (if applicable)
    browser_url: str = ""
    browser_page_title: str = ""
    browser_domain: str = ""
    url_category: str = ""
    
    # Project (if applicable)
    project_name: str = ""
    project_path: str = ""
    current_file: str = ""
    
    # Metadata
    timestamp: str = ""
    is_idle: bool = False  # True если screensaver or locked


def get_snapshot() -> ContextSnapshot:
    """Get a complete context snapshot.
    
    Costs: ~50-100ms (AppleScript calls)
    Call this every 5-10 seconds, not every request.
    """
    snapshot = ContextSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    
    try:
        # 1. Active app (fast, ~10ms)
        app = get_active_app()
        snapshot.app_name = app.get("name", "")
        snapshot.app_bundle_id = app.get("bundle_id", "")
        snapshot.app_pid = app.get("pid", 0)
        snapshot.app_category = get_app_category(snapshot.app_bundle_id)
        
        # 2. Window info (~20ms)
        window = get_focused_window()
        snapshot.window_title = window.get("title", "")
        snapshot.is_fullscreen = window.get("is_fullscreen", False)
        
        # 3. Browser URL (~100ms, only if browser is active)
        if snapshot.app_category == "browser":
            url_info = get_browser_url(snapshot.app_name)
            snapshot.browser_url = url_info.get("url", "")
            snapshot.browser_page_title = url_info.get("title", "")
            snapshot.browser_domain = url_info.get("domain", "")
            snapshot.url_category = classify_url(snapshot.browser_domain)
        
        # 4. Project detection (~10ms)
        if snapshot.app_category in ("ide", "terminal"):
            if snapshot.app_name in ("VS Code", "Code", "Visual Studio Code", "VS Code Insiders"):
                project = detect_vscode_project(snapshot.window_title)
            else:
                project = detect_terminal_project(snapshot.window_title)
            snapshot.project_name = project.get("project", "")
            snapshot.project_path = project.get("path", "")
            snapshot.current_file = project.get("file", "")
        
    except Exception as exc:
        logger.warning("Context snapshot failed: %s", exc)
    
    return snapshot


def format_context_for_prompt(snapshot: ContextSnapshot) -> str:
    """Format the context snapshot for LLM system prompt insertion."""
    parts = []
    parts.append(f"Active app: {snapshot.app_name} ({snapshot.app_category})")
    
    if snapshot.window_title:
        parts.append(f"Window: {snapshot.window_title}")
    
    if snapshot.browser_url:
        parts.append(f"URL: {snapshot.browser_url}")
        parts.append(f"Page: {snapshot.browser_page_title}")
    
    if snapshot.project_name:
        parts.append(f"Project: {snapshot.project_name}")
        if snapshot.current_file:
            parts.append(f"Editing: {snapshot.current_file}")
    
    return " | ".join(parts)
```

### 3.7 `history.py` — история контекста

```python
"""Context history — кольцевой буфер последних N снимков контекста.

Позволяет LLM видеть, что менялось за последние несколько минут.
"""

import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from context_engine.snapshot import ContextSnapshot

logger = logging.getLogger(__name__)

# Ring buffer
MAX_HISTORY = 60  # ~5 минут при 5s интервале
_context_history: deque[ContextSnapshot] = deque(maxlen=MAX_HISTORY)


def record_snapshot(snapshot: ContextSnapshot) -> None:
    """Add a snapshot to the history buffer."""
    _context_history.append(snapshot)


def get_recent_changes(minutes: int = 5) -> list[dict[str, Any]]:
    """Get list of context changes in the last N minutes.
    
    Returns only snapshots where the app or URL changed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    changes = []
    last_app = ""
    last_url = ""
    
    for snap in _context_history:
        try:
            ts = datetime.fromisoformat(snap.timestamp)
            if ts < cutoff:
                continue
        except (ValueError, TypeError):
            continue
        
        if snap.app_name != last_app or snap.browser_url != last_url:
            changes.append({
                "time": snap.timestamp,
                "app": snap.app_name,
                "url": snap.browser_url,
                "project": snap.project_name,
            })
            last_app = snap.app_name
            last_url = snap.browser_url
    
    return changes


def get_context_summary() -> str:
    """Get a human-readable summary of recent context activity."""
    if not _context_history:
        return "No context data yet."
    
    latest = _context_history[-1]
    lines = [
        f"Current: {latest.app_name}",
    ]
    if latest.window_title:
        lines.append(f"Window: {latest.window_title}")
    if latest.browser_url:
        lines.append(f"URL: {latest.browser_url}")
    if latest.project_name:
        lines.append(f"Project: {latest.project_name}")
    
    return " | ".join(lines)
```

### 3.8 `config.py`

```python
"""Context Engine configuration."""

# How often to poll context (seconds)
CONTEXT_POLL_INTERVAL = 5.0  # Каждые 5 секунд

# Thresholds
IDLE_APP_THRESHOLD_MINUTES = 10  # Считаем idle если приложение не менялось 10 минут
FULLSCREEN_APPS = ["com.apple.Screensaver", "com.apple.loginwindow"]

# Browser bundle IDs (для URL детекции)
BROWSER_BUNDLE_IDS = {
    "com.google.Chrome": "Google Chrome",
    "com.apple.Safari": "Safari",
    "company.thebrowser.Browser": "Arc",
    "com.microsoft.edgemac": "Microsoft Edge",
    "org.mozilla.firefox": "Firefox",
}

# Suggestions will be throttled if the user is in a focus category
FOCUS_CATEGORIES = {"ide", "terminal", "design"}  # Don't interrupt these
```

---

## 4. УЛУЧШЕННЫЙ SUGGESTION ENGINE

### 4.1 Новая архитектура

```python
# orchestrator/suggestion_engine_v2.py

class SuggestionEngine:
    """Улучшенный Suggestion Engine с контекстной осведомлённостью."""
    
    def __init__(self):
        self.conversation_history: list[dict] = []
        self.profile: dict | None = None
        self.reward_history: list[dict] = []
        self.last_suggestion_time: float = 0
        self.consecutive_dismissals: int = 0
        self.adaptive_interval: float = 30.0  # Начинаем с 30s
        self.context: ContextSnapshot | None = None
    
    def tick(self) -> list[dict]:
        """Главный вызов. Возвращает список предложений (обычно 0 или 1)."""
        
        # 1. Быстрые проверки (без LLM)
        if not self._should_suggest():
            return []
        
        # 2. Собрать контекст
        context = get_snapshot()
        record_snapshot(context)
        self.context = context
        
        # 3. Выбрать стратегию на основе контекста
        strategy = self._select_strategy(context)
        
        # 4. Сгенерировать предложение (LLM)
        suggestion = self._generate_suggestion(strategy, context)
        
        if suggestion:
            self.last_suggestion_time = time.time()
            return [suggestion]
        return []
    
    def _should_suggest(self) -> bool:
        """Быстрая проверка: стоит ли вообще предлагать?"""
        
        # Не предлагать если пользователь в фулскрин
        if self.context and self.context.is_fullscreen:
            return False
        
        # Не предлагать если занят (thinking/working)
        if current_job["state"] in ("thinking", "working"):
            return False
        
        # Не предлагать если в focus-приложении
        if self.context and self.context.app_category in FOCUS_CATEGORIES:
            # Но можно если проект не менялся 5+ минут (залип)
            changes = get_recent_changes(minutes=5)
            if changes:
                return False
        
        # Rate limiting: не чаще чем раз в adaptive_interval
        if time.time() - self.last_suggestion_time < self.adaptive_interval:
            return False
        
        return True
    
    def _select_strategy(self, context: ContextSnapshot) -> str:
        """Выбрать стратегию на основе контекста."""
        
        # Context-aware триггеры (новые)
        if context.url_category == "development":
            return "code_review"  # На GitHub → предложить review PR
        elif context.url_category == "email":
            return "email_summary"  # В Gmail → предложить прочитать письма
        elif context.url_category == "media":
            return "dnd"  # Смотрит YouTube → не мешать
        elif context.url_category == "social":
            return "social"  # В Twitter → предложить сохранить контент
        elif context.app_category == "ide":
            return "dev_assist"  # В IDE → предложить помощь
        elif context.app_category == "terminal":
            return "dev_assist"  # В Terminal → предложить оптимизацию
        
        # Старые триггеры (как fallback)
        if self.profile and self.last_suggestion_time == 0:
            return "profile"  # Первый раз
        
        if len(self.conversation_history) >= 6:
            return "pattern"  # Есть история
        
        return "ambient"  # Обычный тик
    
    def _generate_suggestion(self, strategy: str, context: ContextSnapshot) -> dict | None:
        """Generate a suggestion using LLM with context-aware prompt."""
        
        prompt = self._build_prompt(strategy, context)
        context_for_llm = format_context_for_prompt(context)
        
        text = _call_llm_sync(prompt, context_for_llm)
        suggestions = _parse_suggestions(text)
        
        if suggestions:
            suggestions[0]["strategy"] = strategy
            suggestions[0]["context_snapshot"] = {
                "app": context.app_name,
                "url": context.browser_url,
                "project": context.project_name,
            }
        
        return suggestions[0] if suggestions else None
    
    def _build_prompt(self, strategy: str, context: ContextSnapshot) -> str:
        """Build a context-aware prompt based on the strategy."""
        
        base = "You are a proactive digital twin.\n\n"
        context_str = format_context_for_prompt(context)
        
        STRATEGY_PROMPTS = {
            "code_review": (
                f"Current context: {context_str}\n"
                "The user is looking at code on GitHub. "
                "Suggest: reviewing a PR, checking CI status, or exploring a repo. "
                "Don't suggest if this is their own repo (they're already working)."
            ),
            "email_summary": (
                f"Current context: {context_str}\n"
                "The user is in their email. "
                "Suggest: summarizing unread emails, drafting a reply, "
                "or flagging an important thread."
            ),
            "dnd": (
                "The user is watching media. Don't suggest anything. "
                "Return empty suggestions."
            ),
            "dev_assist": (
                f"Current context: {context_str}\n"
                f"The user is in {context.app_name}. "
                "Suggest: running tests, checking git status, "
                "or searching for documentation on what they're working on. "
                "Be specific about the project."
            ),
            "social": (
                f"Current context: {context_str}\n"
                "The user is browsing social media. "
                "Suggest: saving an interesting post to Obsidian, "
                "or researching a topic they're looking at."
            ),
            "profile": self._PROFILE_PROMPT,
            "pattern": self._PATTERN_PROMPT,
            "ambient": self._AMBIENT_PROMPT,
        }
        
        prompt_body = STRATEGY_PROMPTS.get(
            strategy,
            "Suggest something helpful based on the current context.",
        )
        
        return base + prompt_body + (
            "\n\nReturn a JSON object with a 'suggestions' array. "
            "Each suggestion has: title, description, confidence (0.0-1.0), "
            "action_id, context (dict). "
            "Only suggest if confidence > 0.7. "
            "If nothing valuable, return {\"suggestions\": []}."
        )
    
    def record_reward(self, action: str, suggestion_id: str) -> None:
        """Record user feedback and adjust behavior."""
        
        if action == "dismiss":
            self.consecutive_dismissals += 1
            # Adaptive backoff
            if self.consecutive_dismissals >= 2:
                self.adaptive_interval = min(
                    self.adaptive_interval * 2, 120.0
                )
                logger.info(
                    "Adaptive backoff: %d dismissals, interval -> %.0fs",
                    self.consecutive_dismissals, self.adaptive_interval,
                )
        elif action == "accept":
            self.consecutive_dismissals = 0
            self.adaptive_interval = max(30.0, self.adaptive_interval / 2)
            logger.info(
                "Suggestion accepted, interval -> %.0fs",
                self.adaptive_interval,
            )
        
        # Save to rewards file
        self._save_reward(action, suggestion_id)
```

---

## 5. ИНТЕГРАЦИЯ С ORCHESTRATOR

### 5.1 Новый ambient loop

```python
# В orchestrator/server.py

from context_engine.snapshot import get_snapshot, format_context_for_prompt
from context_engine.history import get_recent_changes
from suggestion_engine_v2 import SuggestionEngine

# Инициализация
suggestion_engine = SuggestionEngine()

async def _ambient_loop_v2():
    """Улучшенный ambient loop с context detection."""
    await asyncio.sleep(5)  # Стабилизация
    
    while True:
        await asyncio.sleep(CONTEXT_POLL_INTERVAL)  # 5s
        
        try:
            # 1. Получить контекст (быстро, ~50ms)
            context = get_snapshot()
            record_snapshot(context)
            
            # 2. Обновить suggestion engine
            suggestion_engine.context = context
            
            # 3. Проверить, стоит ли предлагать
            if current_job["state"] in ("thinking", "working"):
                continue
            
            if context.is_fullscreen:
                continue
            
            # 4. Контекст изменился? Если нет, можно не предлагать
            changes = get_recent_changes(minutes=2)
            if not changes and time.time() - suggestion_engine.last_suggestion_time < 60:
                continue
            
            # 5. Сгенерировать предложение (LLM)
            suggestions = await asyncio.to_thread(suggestion_engine.tick)
            for suggestion in suggestions:
                await broadcast_event("suggestion", suggestion)
        
        except Exception as exc:
            logger.warning("Ambient loop error: %s", exc)
            await asyncio.sleep(30)
```

### 5.2 Новые инструменты для LLM

```python
# В ALL_TOOLS добавить:

CONTEXT_TOOLS = [
    {
        "name": "get_context",
        "description": "Get the current desktop context: active app, browser URL, project, window title. "
                       "Use this BEFORE suggesting actions or answering 'what am I doing'.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_context_history",
        "description": "Get recent context changes (app switches, URL changes) in the last N minutes. "
                       "Use this to understand what the user has been doing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "description": "Minutes to look back (default 10)"},
            },
        },
    },
]
```

### 5.3 В system prompt

```python
# В build_system_prompt() добавить секцию:

def _get_context_section() -> str:
    """Build the 'current context' section for the system prompt."""
    try:
        context = get_snapshot()
        if not context.app_name:
            return ""
        
        parts = [f"Active: {context.app_name}"]
        if context.window_title:
            parts.append(f"Window: \"{context.window_title}\"")
        if context.browser_url:
            parts.append(f"URL: {context.browser_url}")
        if context.project_name:
            parts.append(f"Project: {context.project_name}")
        
        return "CURRENT CONTEXT:\n" + "\n".join(parts)
    except Exception:
        return ""
```

---

## 6. SUGGESTION RULES (ЛОГИКА ПРИНЯТИЯ РЕШЕНИЙ)

### 6.1 Когда НЕ предлагать

| Условие | Причина |
|---------|---------|
| Пользователь в фулскрин-приложении | Смотрит кино, играет |
| Пользователь в IDE (IDE) И проект менялся < 5 мин назад | Активно кодит |
| `current_job["state"]` = thinking/working | FOL уже что-то делает |
| Последнее предложение < adaptive_interval назад | Rate limit |
| 3+ последовательных dismiss | Пользователь раздражён |
| Активное приложение = screensaver/locked | Пользователя нет |

### 6.2 Когда предлагать

| Контекст | Что предложить | Приоритет |
|----------|---------------|-----------|
| GitHub → PR page | Review PR, check CI | High |
| Gmail | Summarize inbox | Medium |
| VS Code, файл не менялся 5+ мин | Run tests, git status, docs | Medium |
| YouTube / Netflix | Ничего (DND) | Low |
| Slack | Summarize unread messages | Medium |
| Obsidian | Suggest linking notes, daily review | Medium |
| Terminal, после команды | Suggest optimization, error check | High |
| Twitter/X | Save thread to Obsidian | Low |
| Ничего не менялось 10+ мин | Awake check, suggest something | Low |

### 6.3 Adaptive interval

```
Начало:        30s
После accept:  max(15s, interval / 2)  →  быстрее
После dismiss: min(120s, interval * 2) →  медленнее
Максимум:      120s (2 минуты)
Минимум:       15s
Сброс:         30s (если accept после серии dismiss)
```

---

## 7. ПЛАН РЕАЛИЗАЦИИ (BUILD ORDER)

### Phase 3a: Context Engine (базовый)

1. **`context_engine/config.py`** — конфигурация
2. **`context_engine/app_monitor.py`** — определение активного приложения через AppleScript
3. **`context_engine/window_analyzer.py`** — заголовок окна
4. **`context_engine/browser_url.py`** — URL из браузеров
5. **`context_engine/snapshot.py`** — объединение в ContextSnapshot
6. **`context_engine/history.py`** — кольцевой буфер + изменения
7. **Тесты** — `tests/test_context_engine.py`
   - Mock AppleScript outputs
   - Test all browser parsers
   - Test project detection
   - Test URL classification

### Phase 3b: Suggestion Engine V2

8. **`orchestrator/suggestion_engine_v2.py`** — новая архитектура
9. Интеграция `context_engine` в `suggestion_engine_v2`
10. Контекстно-зависимые стратегии
11. **Тесты** — `tests/test_suggestion_engine_v2.py`

### Phase 3c: Интеграция в orchestrator

12. Добавить `get_context` и `get_context_history` в ALL_TOOLS
13. Обновить `_ambient_loop` на v2
14. Обновить `build_system_prompt` с секцией CURRENT CONTEXT
15. Добавить контекстные стратегии в suggestion prompts
16. **Тесты** — интеграционные тесты

---

## 8. ПРОИЗВОДИТЕЛЬНОСТЬ

| Операция | Время | Частота |
|----------|-------|---------|
| `get_active_app()` | ~10ms | Каждые 5s |
| `get_focused_window()` | ~20ms | Каждые 5s |
| `get_browser_url()` | ~100ms | Только когда браузер активен |
| `get_snapshot()` | ~50-130ms | Каждые 5s |
| LLM вызов (suggestion) | ~1-3s | Каждые 30-120s |
| Скриншот (старый метод) | ~100ms | Убрали из тика |

**Итого:** Context poll ~50-130ms каждые 5s. LLM для предложений ~1-3s каждые 30-120s.
Это **на порядок легче** старого метода (скриншот каждые 30s + LLM вызов каждый раз).

---

## 9. СРАВНЕНИЕ: СТАРЫЙ VS НОВЫЙ

| Аспект | Старый (Phase 2) | Новый (Phase 3) |
|--------|-----------------|-----------------|
| Контекст приложения | Нет | Есть (NSWorkspace) |
| URL из браузера | Нет | Есть (AppleScript) |
| Проект из IDE | Нет | Есть (парсинг заголовков) |
| История контекста | Нет | Есть (кольцевой буфер) |
| Скриншот | Каждые 30s | Только по запросу |
| LLM вызов | Каждые 30s | Каждые 30-120s |
| Adaptive interval | Нет | Есть (на основе reward) |
| Фулскрин-детекция | Нет | Есть |
| Контекстные стратегии | Нет | 8 стратегий |
| DND режим | Нет | Авто (IDE, media) |

---

*Phase 3 — FOL начинает видеть, что делает пользователь.*
*Не скриншотом, а через нативные macOS API.*
*Быстрее, легче, релевантнее.*
