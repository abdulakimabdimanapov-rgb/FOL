# FOL — Roadmap: 5 Major Features Implementation Plan

> Дата: August 17, 2026
> Порядок реализации определён по зависимостям: сначала фичи, которые используются другими.

---

## Зависимости между фичами

```
Self-analysis ─────────────┐
                           ├── используется всеми
Multi-Agent (8 агентов) ───┤
                           │
Voice Engine (TTS+STT) ────┤── независим
                           │
Plugin System + Modes ─────┤── зависит от Multi-Agent (режимы фильтруют агентов)
                           │
Mobile Companion ──────────┘── зависит от WebSocket bridge + Voice Engine
```

**Рекомендуемый порядок:**
1. **Self-analysis** — базовая фича, используется всеми агентами
2. **Multi-Agent System** — расширение с 6 → 8+ агентов
3. **Voice Engine** — независимый, нужен для Mobile
4. **Plugin System + Modes** — зависит от Multi-Agent
5. **Mobile Companion** — финальная фича, зависит от Voice + Bridge

---

## 1. Self-analysis (post-task journaling)

### Что это
После каждой выполненной задачи FOL записывает анализ: что получилось, ошибки, что улучить, чему научился. Это делает ассистента «умнее» с опытом.

### Текущее состояние
- `_log_episodic_event(task)` в `orchestrator/server.py` — логирует только текст задачи
- `Brain.record_turn()` — записывает user/FOL对话 в Work-Log
- `_log_episodic_event` вызывается после agent loop completion

### Архитектура

```
Task completed
    │
    ▼
SelfAnalyzer.analyze(task, tools_used, result, errors)
    │
    ├──► Work-Log/YYYY-MM-DD.md   (расширенная запись)
    ├──► Brain/Lessons.md          (повторяющиеся паттерны)
    └──► Obsidian/Daily/YYYY-MM-DD.md  (итоговый блок)
```

### Новые файлы

| Файл | Описание |
|------|----------|
| `fol/modules/llm/self_analysis.py` | `SelfAnalyzer` — LLM-based анализ завершённых задач |
| `orchestrator/self_analysis_bridge.py` | Мост: orchestrator → SelfAnalyzer |
| `tests/test_self_analysis.py` | Unit-тесты |

### SelfAnalyzer — ключевой класс

```python
class SelfAnalyzer:
    """Post-task self-analysis engine."""
    
    async def analyze(
        self,
        task: str,
        tools_used: list[tuple[str, dict]],
        result: str,
        errors: list[str] | None = None,
    ) -> TaskAnalysis:
        """Analyze a completed task via LLM."""
        ...
    
    def record_lesson(self, lesson: str, category: str) -> None:
        """Record a reusable lesson in Brain/Lessons.md."""
        ...
    
    def get_relevant_lessons(self, task: str, limit: int = 5) -> list[str]:
        """Retrieve past lessons relevant to the current task."""
        ...
```

### TaskAnalysis (dataclass)

```python
@dataclass
class TaskAnalysis:
    outcome: str           # "success" | "partial" | "failure"
    what_worked: list[str]  # что получилось
    what_failed: list[str]  # что пошло не так
    lessons: list[str]       # что запомнить
    improvements: list[str]  # что улучить в следующий раз
    tools_efficiency: dict   # какие инструменты были эффективны
```

### Интеграция

1. **`orchestrator/server.py`** — в `run_agent_loop` после completion:
   ```python
   analysis = await self_analyzer.analyze(task, executed_tools, result, errors)
   if analysis.lessons:
       for lesson in analysis.lessons:
           self_analyzer.record_lesson(lesson, category)
   ```

2. **`fol/core/app.py`** — в `process()` после LLM response:
   ```python
   if self._self_analyzer:
       await self._self_analyzer.analyze_post_response(user_input, final)
   ```

3. **Brain/Lessons.md** — автоматически обновляется:
   ```markdown
   ## Lessons
   - **2026-08-17** [coding] Always check existing tests before modifying functions
   - **2026-08-17** [browser] cookie sync needed before first navigation
   ```

4. **System prompt** — релевантные Lessons подгружаются в context:
   ```python
   lessons = self_analyzer.get_relevant_lessons(task)
   if lessons:
       sections.append(f"PAST LESSONS:\n" + "\n".join(f"- {l}" for l in lessons))
   ```

### Этапы

| Этап | Описание | Зависимости |
|------|----------|-------------|
| 1.1 | `SelfAnalyzer` + `TaskAnalysis` | — |
| 1.2 | LLM-промпт для анализа | 1.1 |
| 1.3 | Brain/Lessons.md запись | 1.1 |
| 1.4 | Интеграция в orchestrator | 1.1, 1.2 |
| 1.5 | Интеграция в FOL core | 1.1 |
| 1.6 | System prompt injection | 1.3 |
| 1.7 | Unit-тесты | 1.1-1.6 |

---

## 2. Multi-Agent System (расширение с 6 → 8+ агентов)

### Текущее состояние
- 6 агентов: General, Architect, Coder, Reviewer, Researcher, Memory
- `orchestrator/agents/router.py` — keyword/fuzzy/bilingual routing
- `orchestrator/agents/*.py` — промпты + tool subsets
- `_AGENT_REGISTRY` в `server.py` — маппинг тип → config

### Новые агенты

| Агент | Роль | Ключевые слова |
|-------|------|----------------|
| **Planner** | Планирование, roadmap, milestones, time management | plan, roadmap, milestone, schedule, plan, распис, план, этап |
| **Automation** | Скрипты автоматизации, пайплайны, cron, workflows | automate, script, workflow, pipeline, cron, автоматиз, скрипт, пайплайн |
| **Documentation** | Документация, README, комментарии, SPEC | document, docs, readme, comment, документ, опиши, комментар, spec |

### Архитектура

```
orchestrator/agents/
├── __init__.py           # AgentType enum + exports
├── router.py             # Routing (6 → 9 типов)
├── architect.py          # ✅ существующий
├── coder.py              # ✅ существующий
├── reviewer.py           # ✅ существующий
├── researcher.py         # ✅ существующий
├── memory.py             # ✅ существующий
├── planner.py            # 🆕 Planner Agent
├── automation.py         # 🆕 Automation Agent
├── documentation.py      # 🆕 Documentation Agent
└── base.py               # 🆕 Base agent class (DRY)
```

### `base.py` — общий базовый класс

```python
class BaseAgent:
    """Base class for all specialized agents."""
    
    name: str = "base"
    prompt: str = ""
    tool_names: set[str] = set()
    
    def get_prompt_suffix(self) -> str:
        return self.prompt
    
    def get_tools(self, all_tools: list[dict]) -> list[dict]:
        if not self.tool_names:
            return all_tools
        return [t for t in all_tools if t["name"] in self.tool_names]
```

### Обновление router.py

```python
class AgentType(str, Enum):
    ARCHITECT = "architect"
    CODER = "coder"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"
    MEMORY = "memory"
    PLANNER = "planner"          # 🆕
    AUTOMATION = "automation"    # 🆕
    DOCUMENTATION = "documentation"  # 🆕
    GENERAL = "general"
```

Добавить в `_ROUTES`:
```python
# Planner (после Researcher)
(["plan", "roadmap", "milestone", "schedule", "plan", "распис", "план", "этап", 
  "timeline", "deadline", "приоритет", "priority"], AgentType.PLANNER),

# Automation (после Planner)
(["automate", "script", "workflow", "pipeline", "cron", "автоматиз", "скрипт", 
  "пайплайн", "задач", "task scheduler"], AgentType.AUTOMATION),

# Documentation (после Automation)
(["document", "docs", "readme", "comment", "документ", "опиши", "комментар", 
  "spec", "документац", "инструкци"], AgentType.DOCUMENTATION),
```

### Tool subsets для новых агентов

```python
# planner.py
PLANNER_TOOLS_NAMES = {
    "render_task_approval", "render_profile_card",
    "search_web", "browser_goto",
    "save_to_obsidian", "get_daily_summary",
    "create_event", "list_events",
}

# automation.py  
AUTOMATION_TOOLS_NAMES = {
    "execute_command", "open_app", "close_app",
    "type_text", "hotkey", "screenshot",
    "browser_goto", "browser_click", "browser_fill",
    "scheduler_tool", "notify",
}

# documentation.py
DOCUMENTATION_TOOLS_NAMES = {
    "read_file", "write_file", "search_files",
    "browser_goto", "browser_snapshot",
    "save_to_obsidian", "render_task_approval",
}
```

### Этапы

| Этап | Описание |
|------|----------|
| 2.1 | `base.py` — общий базовый класс |
| 2.2 | `planner.py` + промпт + tool subset |
| 2.3 | `automation.py` + промпт + tool subset |
| 2.4 | `documentation.py` + промпт + tool subset |
| 2.5 | `router.py` — добавить 3 новых AgentType + ключевых слова |
| 2.6 | `__init__.py` — обновить экспорты |
| 2.7 | `server.py` — `_AGENT_REGISTRY` + `_select_tools_for_task` |
| 2.8 | Unit-тесты для router (расширить `test_router.py`) |

---

## 3. Voice Engine (TTS + STT + фоновый режим)

### Текущее состояние
- **STT**: `fol/modules/input/voice/stt.py` — MLX Whisper (local) + ElevenLabs (cloud)
- **TTS**: `fol/modules/output/tts.py` — MacOSSay + ElevenLabs
- **Voice Assistant**: `fol/modules/input/speech.py` — VoiceAssistant (wake word,录音, transcription)
- **SwiftUI**: `AudioRecorder.swift`, `SpeechService.swift`, `ElevenLabsService.swift`, `LocalSTTService.swift`
- **FOL API**: `POST /api/stt` — transcription endpoint

### Проблемы
1. STT и TTS — разные модули, нет единого контракта
2. Нет фонового режима (wake word → continuous listening)
3. Нет unified VoiceEngine
4. SwiftUI VoiceInputButton не интегрирован с FOL core

### Архитектура

```
┌─────────────────────────────────────────────┐
│              VoiceEngine (единый контракт)   │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │ STT      │  │ TTS      │  │ Wake Word │ │
│  │ (local/  │  │ (say/    │  │ (snowboy/ │ │
│  │  cloud)  │  │  eleven) │  │  porcupine│ │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘ │
│       │              │              │        │
│  ┌────▼──────────────▼──────────────▼────┐  │
│  │         EventBus Integration          │  │
│  │  VOICE_LISTENING / VOICE_TRANSCRIBED  │  │
│  │  VOICE_SPEAKING / WAKE_WORD_DETECTED  │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

### Новые файлы

| Файл | Описание |
|------|----------|
| `fol/modules/input/voice/engine.py` | `VoiceEngine` — unified voice controller |
| `fol/modules/input/voice/wake_word.py` | `WakeWordDetector` — wake word detection |
| `fol/modules/input/voice/background.py` | `BackgroundListener` — continuous listening mode |
| `tests/test_voice_engine.py` | Unit-тесты |

### VoiceEngine — ключевой класс

```python
class VoiceEngine:
    """Unified voice engine — STT + TTS + Wake Word in one interface."""
    
    def __init__(self):
        self._stt = get_stt()           # MLX Whisper / ElevenLabs
        self._tts = get_tts()           # MacOSSay / ElevenLabs
        self._wake = WakeWordDetector()  # "FOL" / custom
        self._background = None          # BackgroundListener (lazy)
        self._state = VoiceState.IDLE
    
    async def start_listening(self) -> None:
        """Start continuous listening mode."""
        ...
    
    async def stop_listening(self) -> None:
        """Stop continuous listening."""
        ...
    
    async def transcribe_file(self, path: str) -> str:
        """Transcribe an audio file."""
        ...
    
    async def speak(self, text: str) -> bool:
        """Speak text aloud."""
        ...
    
    async def speak_and_wait(self, text: str) -> bool:
        """Speak text and wait for completion."""
        ...
    
    @property
    def is_listening(self) -> bool:
        ...
    
    @property
    def is_speaking(self) -> bool:
        ...
```

### BackgroundListener

```python
class BackgroundListener:
    """Continuous listening mode — records chunks, transcribes on silence."""
    
    def __init__(self, engine: VoiceEngine):
        self._engine = engine
        self._running = False
        self._silence_threshold = 0.02
        self._silence_duration = 1.5  # seconds
    
    async def start(self) -> None:
        """Start background listening loop."""
        self._running = True
        while self._running:
            # Record audio chunk
            # Detect silence
            # On silence: transcribe chunk → emit event
            ...
    
    async def stop(self) -> None:
        self._running = False
```

### Интеграция с FOL core

```python
# fol/core/app.py — _init_voice()
async def _init_voice(self) -> None:
    from modules.input.voice.engine import VoiceEngine
    self._voice_engine = VoiceEngine()
    # Subscribe to voice events
    self.event_bus.subscribe(EventType.WAKE_WORD_DETECTED, self._on_wake_word)
    self.event_bus.subscribe(EventType.VOICE_TRANSCRIBED, self._on_voice_input)
```

### Интеграция с SwiftUI

SwiftUI уже имеет `LocalSTTService` и `AudioRecorder`. Изменения минимальны:
- `LocalSTTService` уже вызывает `POST /api/stt` → FOL API
- FOL API `speech_to_text()` уже делегирует в `modules.input.voice.stt`
- Добавить `POST /api/tts` endpoint для TTS из SwiftUI

### Этапы

| Этап | Описание |
|------|----------|
| 3.1 | `VoiceEngine` — unified class |
| 3.2 | `WakeWordDetector` — wake word detection |
| 3.3 | `BackgroundListener` — continuous listening |
| 3.4 | EventBus integration (VOICE_* events) |
| 3.5 | FOL API `/api/tts` endpoint |
| 3.6 | FOL core integration |
| 3.7 | SwiftUI voice bridge (опционально) |
| 3.8 | Unit-тесты |

---

## 4. Plugin System + Modes

### Текущее состояние
- **Plugin System**: `fol/modules/plugins/` — полная реализация
  - `FOLPlugin` base class with hooks
  - `PluginManager` — lifecycle, enable/disable, hooks
  - `PluginLoader` — filesystem discovery
  - `PluginManifest` — metadata from manifest.json
- **Modes**: `fol/core/app.py` — 4 режима (companion/assistant/agent/focus)
  - `_MODE_ALIASES`, `_MODE_LABELS_*`, `_MODE_DESCRIPTIONS_*`
  - `_MODE_CONTEXT_HINTS` — LLM context per mode
  - `_set_mode()`, `_mode_status()`

### Что нужно сделать

#### 4a. Расширение Modes до 6

| Режим | Описание | Включённые инструменты |
|-------|----------|----------------------|
| companion | обычное общение | все |
| assistant | выполняю задачи | все |
| agent | многошаговые задачи | все |
| focus | минимум разговоров | все (короткие ответы) |
| **development** 🆕 | разработка | VS Code, Terminal, GitHub, Docker, browser |
| **research** 🆕 | исследование | browser, Tavily, Calendar, Obsidian |

#### 4b. Plugin-Driven Modes

Режимы управляются через plugins — каждый режим это plugin, который:
- Фильтрует доступные инструменты
- Меняет system prompt
- Настраивает personality layer

```python
# fol/modules/plugins/modes/development.py
class DevelopmentMode(FOLPlugin):
    name = "mode_development"
    
    TOOL_FILTER = {
        "open_app", "type_text", "hotkey", "screenshot",
        "browser_goto", "browser_snapshot", "browser_click",
        "execute_command", "read_file", "write_file", "search_files",
        "save_to_obsidian", "notify",
    }
    
    SYSTEM_PROMPT_ADDITION = """
    CURRENT MODE: Development — you are in coding mode. 
    Focus on code quality, testing, and clean architecture.
    Prefer terminal and IDE tools over browser.
    """
    
    async def before_llm_call(self, messages):
        # Filter tools to development subset
        ...
```

#### 4c. Plugin Connectors (конкретные плагины)

| Plugin | Описание |
|--------|----------|
| `github` | GitHub API: repos, issues, PRs |
| `vscode` | VS Code integration: open files, extensions |
| `docker` | Docker: containers, images, compose |
| `telegram` | Telegram bot: send/receive messages |

### Новые файлы

| Файл | Описание |
|------|----------|
| `fol/modules/plugins/modes/development.py` | Development mode plugin |
| `fol/modules/plugins/modes/research.py` | Research mode plugin |
| `fol/modules/plugins/connectors/github.py` | GitHub connector plugin |
| `fol/modules/plugins/connectors/docker.py` | Docker connector plugin |
| `fol/modules/plugins/connectors/telegram.py` | Telegram connector plugin |
| `tests/test_modes.py` | Mode tests |
| `tests/test_plugins.py` | Plugin tests |

### Этапы

| Этап | Описание |
|------|----------|
| 4.1 | Добавить `development` и `research` в `_MODE_ALIASES` |
| 4.2 | Создать `DevelopmentMode` plugin |
| 4.3 | Создать `ResearchMode` plugin |
| 4.4 | Создать `GitHubConnector` plugin |
| 4.5 | Создать `DockerConnector` plugin |
| 4.6 | Создать `TelegramConnector` plugin |
| 4.7 | Интеграция modes → tool filtering в orchestrator |
| 4.8 | Unit-тесты |

---

## 5. Mobile Companion (iOS)

### Текущее состояние
- SwiftUI macOS приложение (`fol-app/`) — Notch UI
- WebSocket: `orchestrator/server.py` `GET /events` (SSE)
- FOL API: `POST /api/chat`, `POST /api/stt`, `GET /health`
- Bridge System: в плане (WebSocket Mac ↔ iPhone)

### Архитектура

```
┌─────────────────────────────────────────────┐
│               iPhone (iOS App)               │
│                                              │
│  ┌──────────────┐  ┌─────────────────────┐  │
│  │ Chat UI      │  │ Dynamic Island      │  │
│  │ (SwiftUI)    │  │ (Notch-style)       │  │
│  ├──────────────┤  ├─────────────────────┤  │
│  │ Voice Input  │  │ Quick Actions       │  │
│  │ (AVAudio)    │  │ (Siri-style)        │  │
│  ├──────────────┤  ├─────────────────────┤  │
│  │ Notifications│  │ Status Bar          │  │
│  │ (Push)       │  │ (FOL state)         │  │
│  └──────┬───────┘  └──────────┬──────────┘  │
│         │                     │              │
│  ┌──────▼─────────────────────▼──────────┐  │
│  │         WebSocket Bridge              │  │
│  │    ws://macbook:8420/ws/mobile        │  │
│  └──────────────────┬───────────────────┘  │
└─────────────────────┼───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│            MacBook (FOL Backend)             │
│                                              │
│  Orchestrator :8420                          │
│  ├── WebSocket /ws/mobile (iOS bridge)      │
│  ├── SSE /events (existing)                  │
│  └── POST /chat (existing)                   │
│                                              │
│  FOL API :8754                               │
│  ├── POST /api/stt (STT proxy)              │
│  ├── POST /api/tts (TTS proxy)              │
│  └── GET /health                             │
└──────────────────────────────────────────────┘
```

### Новые файлы

| Файл | Описание |
|------|----------|
| `orchestrator/mobile_bridge.py` | WebSocket bridge для iOS |
| `MobileSelf/` (директория) | iOS приложение |
| `MobileSelf/MobileSelfApp.swift` | Entry point |
| `MobileSelf/Views/ChatView.swift` | Chat UI |
| `MobileSelf/Views/IslandView.swift` | Dynamic Island |
| `MobileSelf/Views/QuickActionsView.swift` | Quick actions |
| `MobileSelf/Services/WebSocketService.swift` | WS connection |
| `MobileSelf/Services/VoiceService.swift` | STT/TTS via FOL API |

### WebSocket Bridge (`mobile_bridge.py`)

```python
class MobileBridge:
    """WebSocket bridge for iOS companion."""
    
    def __init__(self, orchestrator_app):
        self._app = orchestrator_app
        self._connections: list[WebSocket] = []
    
    async def handle_connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connections.append(websocket)
        # Send initial state
        await websocket.send_json({
            "type": "state",
            "twin_state": self._app.twin_state,
            "mode": self._app.mode,
        })
    
    async def handle_message(self, websocket: WebSocket, data: dict):
        if data["type"] == "chat":
            # Forward to orchestrator
            response = await self._app.process(data["message"])
            await websocket.send_json({
                "type": "response",
                "text": response,
            })
        elif data["type"] == "voice":
            # STT via FOL API
            ...
    
    async def broadcast(self, event_type: str, data: dict):
        """Push event to all connected iOS devices."""
        for conn in self._connections:
            await conn.send_json({"type": event_type, **data})
```

### iOS App — Minimal Viable

1. **Chat View** — текстовый чат через WebSocket
2. **Voice Button** — запись → FOL API `/api/stt` → отправка
3. **Dynamic Island** — миниатюрный индикатор состояния FOL
4. **Quick Actions** — быстрые команды (screenshot, status, open app)
5. **Notifications** — Push от FOL (proactive suggestions)

### Этапы

| Этап | Описание |
|------|----------|
| 5.1 | `mobile_bridge.py` — WebSocket endpoint |
| 5.2 | iOS app scaffold (SwiftUI, minimal) |
| 5.3 | Chat View + WebSocket service |
| 5.4 | Voice input → FOL API STT |
| 5.5 | Dynamic Island view |
| 5.6 | Quick Actions |
| 5.7 | Push notifications |
| 5.8 | Memory sync (shared Obsidian) |
| 5.9 | Testing + polish |

---

## Сводная таблица

| # | Feature | Новых файлов | Сложность | Приоритет |
|---|---------|-------------|-----------|-----------|
| 1 | Self-analysis | 3 | ⭐⭐ | 1 (базовая) |
| 2 | Multi-Agent (8+) | 5 | ⭐⭐ | 2 |
| 3 | Voice Engine | 4 | ⭐⭐⭐ | 3 |
| 4 | Plugin System + Modes | 7 | ⭐⭐ | 4 |
| 5 | Mobile Companion | 9+ | ⭐⭐⭐⭐ | 5 |
| **Итого** | | **28+** | | |

---

## Начать реализацию

Рекомендую начать с **Self-analysis** (задача 1) — она:
- Простая (3 файла + интеграция)
- Независимая (не зависит от других фич)
- Полезная сразу (улучшает качество ответов всех агентов)
- Используется всеми последующими фичами

Хочешь начать с Self-analysis или с другой задачи?
