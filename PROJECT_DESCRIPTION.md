# FOL — Проект: полное описание

> **Версия:** 1.2.0 | **Код:** 304k строк | **Python:** 1111 файлов | **Swift:** 66 файлов | **Тесты:** 1111+

---

## Что такое FOL

FOL (Friendly Obedient Listener) — персональный AI-ассистент для macOS, который живёт в вырезе MacBook (Notch UI), понимает контекст экрана, помнит пользователя и выполняет действия на компьютере. По сути — **цифровой двойник** в стиле JARVIS из Iron Man.

**Главная проблема, которую решает FOL:** повседневная работа за компьютером состоит из повторяющихся действий, переключения между приложениями и постоянного объяснения контекста. FOL устраняет это «трение» (friction) тремя способами:

1. **Desktop automation** — открывает приложения, работает с браузером, файлами, кликами
2. **Context + Memory** — помнит контекст и предпочтения, не нужно объяснять одно и то же
3. **Proactive assistance** — сам замечает полезный контекст и предлагает действия

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                        USER LAYER                           │
│  Text Chat · Voice · Notch UI · Dynamic Island · Telegram   │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    SWIFT UI (fol-app/)                      │
│  SwiftUI macOS приложение — NotchPanel, ChatView,           │
│  VoiceInputButton, A2UIRenderer, TwinCharacterView         │
│  NotchPanel (кастомный NSPanel без DynamicNotchKit)        │
│  A2UI протокол — структурированные карточки вместо текста   │
└──────────────────────────┬──────────────────────────────────┘
                           │ SSE / WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                  ORCHESTRATOR (:8420)                        │
│  FastAPI + SSE streaming                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Conversation Engine                                  │    │
│  │   normalize → route → tool selection → LLM → format  │    │
│  │                                                      │    │
│  │ Agent Team (5 агентов):                              │    │
│  │   Architect · Coder · Reviewer · Researcher · Memory │    │
│  │                                                      │    │
│  │ Bilingual Routing (RU + EN)                          │    │
│  │   fuzzy matching · greeting detection · mixed lang   │    │
│  │                                                      │    │
│  │ Two-stage Tool Selection                             │    │
│  │   category → 5-12 tools (из 50)                     │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      BRAIN ROUTER                            │
│  ┌─────────────────┐    ┌──────────────────────┐            │
│  │ Freebuff Brain   │    │ API Fallback          │            │
│  │ (PRIMARY)        │    │ (BACKUP)              │            │
│  │ via OpenRouter   │    │ OpenAI · Anthropic    │            │
│  │ DeepSeek V4      │    │ Gemini · Groq         │            │
│  │ MiMo 2.5         │    │                       │            │
│  └─────────────────┘    └──────────────────────┘            │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    TOOL SYSTEM                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 50 инструментов × 5-уровневый Risk Scorer            │   │
│  │                                                      │   │
│  │ macOS: open_app · close_app · screenshot · notify    │   │
│  │        type_text · hotkey · click · scroll · drag    │   │
│  │        clipboard_get/set · activate_app              │   │
│  │                                                      │   │
│  │ Browser: navigate · search · snapshot · text · goto  │   │
│  │          open · click · type · scroll · screenshot   │   │
│  │          extract · close · refresh · press_key       │   │
│  │                                                      │   │
│  │ Files: read · write · search                         │   │
│  │ Terminal: execute_command                            │   │
│  │ Productivity: email · calendar · documents           │   │
│  │ Memory: obsidian · knowledge graph · preferences     │   │
│  │ Web: search_web · web_scraper · bookmarks            │   │
│  └──────────────────────────────────────────────────────┘   │
│  Safety Gate (ConfirmationGate) — блокирует опасные действия│
│  RiskScorer — 5 уровней: SAFE_READ → STRICT_CONFIRM → REJECT│
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                  AGENT SERVER (:8421)                        │
│  PyAutoGUI + AppleScript — десктоп/браузер контроль        │
│  MJPEG стриминг · browser CDP · cookie sync                │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    FOL API (:8754)                           │
│  Python AI-ядро — JARVIS-команды                           │
│  REST + WebSocket · Proactive Mode · Memory · Context      │
└─────────────────────────────────────────────────────────────┘
```

---

## Структура проекта

```
FOL/
├── fol/                          # Python AI-ядро (главный модуль)
│   ├── core/                     # App · EventBus · Lifecycle · Orchestrator
│   ├── modules/
│   │   ├── llm/                  # Brain · Router · Engine · Personality · Proactive
│   │   ├── brain/                # Freebuff Brain · Process Manager · Startup
│   │   ├── tools/                # 50 инструментов · RiskScorer · ConfirmationGate
│   │   │   ├── browser/          # Browser automation (navigate, search, interact)
│   │   │   ├── mouse_keyboard/   # Mouse · Keyboard controllers
│   │   │   ├── desktop/          # Email · Calendar · Screenshot tools
│   │   │   ├── system/           # ExecuteCommand · FileOps · SystemInfo
│   │   │   └── automation/       # Scheduler · Workflow · Recorder
│   │   ├── memory/               # RAG · Knowledge Graph · Obsidian · Episodic
│   │   │   ├── identity/         # Identity Layers (digital twin)
│   │   │   └── brain.py          # Freebuff Brain — Obsidian-based persistent memory
│   │   ├── input/                # Voice · Vision · Context · Speech (mlx-whisper)
│   │   │   └── voice/            # STT providers (mlx-whisper)
│   │   ├── output/               # TTS · Telegram · Notifications · Display
│   │   └── plugins/              # Plugin system (hooks, loader, manager)
│   ├── api/                      # REST + WebSocket server (:8754)
│   ├── config/                   # Settings · Logging · Constants
│   └── tests/                    # 1073 теста (brain, tools, memory, core, integration)
│
├── fol-app/                      # SwiftUI macOS приложение
│   ├── FOLApp.swift              # Entry point, AppDelegate
│   ├── NotchOverlayController.swift  # Notch UI management
│   ├── NotchPanel.swift          # Кастомный NSPanel
│   ├── Views/                    # UI компоненты (24 Swift файла)
│   │   ├── ChatView.swift        # Чат с анимациями
│   │   ├── ChatInputBar.swift    # Поле ввода + AudioWaveform
│   │   ├── VoiceInputButton.swift # Микрофон с пульсацией
│   │   ├── A2UIRenderer.swift    # A2UI карточки
│   │   ├── RiskConfirmCard.swift # Подтверждение рискованных действий
│   │   └── ...
│   ├── Models/                   # ChatMessage · TwinState · SSEParser
│   ├── Services/                 # AudioRecorder · STT · TTS · ElevenLabs
│   ├── ViewModels/               # Бизнес-логика UI
│   └── Utilities/                # DesignTokens · Extensions
│
├── orchestrator/                 # FastAPI AI-сервер (:8420)
│   ├── server.py                 # Главный файл: LLM + tools + SSE
│   ├── agents/                   # 5 агентов + router + bilingual routing
│   ├── tool_registry.py          # Единый реестр 50 инструментов
│   ├── response_formatter.py     # Санитизация вывода (никогда JSON в чате)
│   ├── llm_bridge.py             # Мост к LiteLLM (sync/async/stream)
│   ├── memory_bridge.py          # Мост к Obsidian памяти
│   └── productivity_tools.py     # Gmail · Calendar · Documents
│
├── agent-server/                 # Десктоп/браузер контроль (:8421)
├── obsidian/                     # Obsidian REST API клиент (v5)
├── src/                          # Next.js web интерфейс (SSE-чат)
├── tests/                        # 38 корневых тестов (router, normalize, server)
├── scripts/                      # E2E · Demo · Smoke test скрипты
├── docs/                         # ARCHITECTURE · MIGRATION · INTERNAL
└── run_all.sh                    # Единый лаунчер всех сервисов
```

---

## Сервисы и порты

| Сервис | Порт | Описание |
|--------|------|----------|
| **Orchestrator** | `:8420` | FastAPI AI-сервер: агенты, tools, memory, SSE streaming |
| **Agent Server** | `:8421` | Десктоп/браузер контроль: PyAutoGUI + AppleScript |
| **FOL API** | `:8754` | Python AI-ядро: JARVIS-команды, REST + WebSocket |
| **Web UI** | `:3000` | Next.js web интерфейс (SSE-чат) |

---

## Brain — Мозг FOL

FOL поддерживает несколько brain-бэкендов через единую абстракцию `BrainInterface`:

| Бэкенд | Класс | Env | Описание |
|--------|-------|-----|----------|
| **current** | `CurrentLLMAdapter` | `FOL_BRAIN=current` | ✅ Рабочий (LiteLLM: OpenRouter/Ollama/MLX) |
| **freebuff** | `FreebuffBrainAdapter` | `FOL_BRAIN=freebuff` | ✅ Рабочий (через OpenRouter: DeepSeek V4, MiMo 2.5) |
| **codebuff** | `CodebuffSDKBrainAdapter` | `FOL_BRAIN=codebuff` | ✅ Рабочий (через `@codebuff/sdk`, платный) |

### Freebuff Brain (PRIMARY)

```
User → FOL → BrainStartupManager → BrainRouter
  ├── FreebuffBrainAdapter (PRIMARY)  →  CurrentLLMAdapter  →  LiteLLMRouter
  │                                        ↓
  │                                    OpenRouter (Freebuff models)
  │                                    - deepseek-v4-flash (free)
  │                                    - mimo-2.5 (free)
  │                                    - nemotron-3-super (free)
  └── CurrentLLMAdapter (FALLBACK)   →  LiteLLMRouter
                                        ↓
                                    OpenAI / Anthropic / Gemini / ...
```

- **Freebuff** — бесплатные модели через OpenRouter
- **Fallback** — автоматическое переключение при отказе
- **Health monitoring** — проверка доступности OpenRouter
- **Crash recovery** — автоматический рестарт с лимитом попыток

---

## 50 инструментов

### macOS Desktop (14)
`open_app` · `close_app` · `activate_app` · `screenshot` · `notify` · `type_text` · `hotkey` · `click` · `scroll` · `drag` · `clipboard_get` · `clipboard_set` · `system_info` · `desktop_screenshot`

### Browser (16)
`browser_goto` · `browser_search` · `browser_snapshot` · `browser_text` · `browser_open` · `browser_click` · `browser_type` · `browser_scroll` · `browser_screenshot` · `browser_extract` · `browser_close` · `browser_refresh` · `browser_press_key` · `safari_goto` · `safari_get_text` · `safari_get_url`

### Productivity (10)
`send_email` · `draft_email` · `reply_to_email` · `read_emails` · `get_contact_info` · `summarize_emails` · `create_event` · `update_event` · `delete_event` · `list_events`

### Memory (6)
`save_to_obsidian` · `search_obsidian` · `get_daily_summary` · `log_daily_activity` · `create_document` · `share_document`

### System (4)
`execute_command` · `search_files` · `read_file` · `write_file`

---

## Билингвальный routing (RU + EN)

FOL понимает русский и английский с混合ным routing:

```
Команда: "review мой код"
  ↓
_is_greeting()          → нет
_bilingual_route()      → mixed (review=EN, мой код=RU)
_classify_by_keywords() → REVIEWER (из-за "review")
  ↓
Agent: Reviewer
```

### 5 агентов

| Агент | EN ключевые слова | RU ключевые слова |
|-------|-------------------|-------------------|
| **Architect** | architecture, design pattern, system design | архитектур, спроектир, схема, тз |
| **Reviewer** | review, check, code review, audit | провер, ревью, качеств, аудит |
| **Coder** | implement, write code, refactor | напиш, код, создай, баг, тест |
| **Researcher** | search, find, what is, explain | найд, поищ, ищи, гугл |
| **Memory** | remember, save, note, remind | запомн, сохран, заметк, напомн |

---

## Безопасность

### 5-уровневый RiskScorer

| Уровень | Категория | Действие |
|---------|-----------|----------|
| **1** | SAFE_READ | Выполняется молча |
| **2** | UI_NAVIGATION | Лёгкое уведомление |
| **3** | INTERACTIVE_GUI | Auto-dismiss уведомление |
| **4** | FILE_MUTATION | Блокировка до подтверждения |
| **5** | SYSTEM_DANGEROUS | Модалка с таймаутом |

### Security-фиксы

- **Race condition** — `asyncio.Lock()` на ConfirmationGate (конкурентные запросы)
- **Shell injection** — `_DANGEROUS_CMD_PATTERNS` (30+ паттернов, fail-closed)
- **Memory leak** — `_max_history = 100` (защита от бесконечного роста)
- **API keys** — никогда не логируются, scrubbed в ошибках

---

## Память и контекст

### Memory Stack

| Слой | Описание |
|------|----------|
| **Conversation History** | Последние 100 ходов диалога |
| **Context Manager** | Отслеживание текущей темы |
| **Knowledge Graph** | Граф знаний (entities + relations) |
| **Episodic Memory** | Эпизоды (что когда произошло) |
| **Preferences Store** | Предпочтения пользователя |
| **Long-term Memory** | Извлечённые факты из диалогов |
| **Obsidian Brain** | Persistent memory в Obsidian vault |
| **Identity Layers** | Цифровой двойник (профиль, цели, проекты) |
| **RAG Pipeline** | Retrieval-Augmented Generation |

### Freebuff Brain (Obsidian-based)

- **Work-Log** — журнал действий по дням
- **Lessons** — извлечённые уроки
- **Model History** — какие модели использовались
- **Profile/Goals** — профиль и цели пользователя

---

## Голосовой интерфейс

| Компонент | Описание |
|-----------|----------|
| **STT** | mlx-whisper (Apple Silicon, офлайн) |
| **TTS** | SPM4040 (системный) + ElevenLabs (облако) |
| **Wake word** | "FOL" — активация по голосу |
| **Voice modes** | Companion · Assistant · Agent · Focus |

---

## UI — Notch Panel

```
┌─────────────────────────────────────────┐
│            MacBook Notch                │
│  ┌─────────────────────────────────┐    │
│  │  ● Freebuff Online              │    │ ← Brain status
│  │                                 │    │
│  │  [User]: Открой Safari          │    │ ← User message
│  │                                 │    │
│  │  [FOL]: Открываю Safari...      │    │ ← Twin response
│  │  ┌──────────────────────┐       │    │
│  │  │  Safari  ● Running   │       │    │ ← A2UI card
│  │  └──────────────────────┘       │    │
│  │                                 │    │
│  │  [Voice ▶] ─────────────── [▶]  │    │ ← Input bar
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

### UI компоненты (24 Swift файла)

- **ChatView** — чат с `.asymmetric` transition (offset + scale + opacity)
- **ChatInputBar** — shimmer/glow эффект, AudioWaveformView (физ. симуляция волн)
- **VoiceInputButton** — пульсация при записи, 2 кольцевых обводки
- **A2UIRenderer** — структурированные карточки (Screenshot, ActionInfo, TaskApproval)
- **RiskConfirmCard** — подтверждение рискованных действий
- **TwinCharacterView** — анимированный персонаж (GIF + позы)
- **NotchViews** — Notch overlay, профиль, настройки

---

## Конфигурация (.env)

```env
# LLM — одна строка
LLM_MODEL=openrouter/deepseek/deepseek-v4-flash
LLM_FALLBACK_MODELS=openrouter/moonshotai/mimo-2.5,openrouter/nvidia/nemotron-3-super-120b-a12b:free
FOL_BRAIN=freebuff    # current | freebuff | codebuff

# Ключи (только API-провайдеры)
OPENROUTER_API_KEY=sk-or-...
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...

# Сервер
HOST=0.0.0.0
PORT=8000
```

---

## Тестирование

```bash
# Все тесты
python3 -m pytest tests/ -v                    # 1111 passed

# Браин
python3 -m pytest tests/brain/ -v              # 35 passed

# Билингвальный роутер
python3 -m pytest tests/test_router.py -v      # 65 passed

# Нормализация текста
python3 -m pytest tests/test_normalize.py -v   # 48 passed

# FOL core
cd fol && python3 -m pytest tests/ -v          # 1073 passed

# Swift сборка
cd fol-app && swift build                       # Build complete
```

### E2E сценарии

```bash
python3 scripts/e2e_check.py                   # 14/14
./scripts/verify_scenarios.sh                   # 5 сценариев
./scripts/demo.sh                               # Демо с паузами
```

---

## Стек технологий

| Компонент | Технологии |
|-----------|------------|
| **AI Core** | Python 3.9+ · LiteLLM · OpenRouter · FastAPI · asyncio |
| **LLM** | DeepSeek V4 Flash · MiMo 2.5 · Nemotron (через OpenRouter) |
| **UI** | SwiftUI · NSPanel · Combine · Swift Package Manager |
| **Voice** | mlx-whisper (STT) · SPM4040/Apple TTS · ElevenLabs (TTS) |
| **Memory** | Obsidian REST API · SQLite · Knowledge Graph · RAG |
| **Desktop** | PyAutoGUI · AppleScript · browser CDP |
| **Web** | Next.js · TypeScript · SSE streaming |
| **Safety** | RiskScorer (5 уровней) · ConfirmationGate · asyncio.Lock |
| **CI/CD** | GitHub Actions · pytest · Swift build · Docker |
| **Билд** | build-app.sh · codesign · .app bundle |

---

## История версий

| Версия | Дата | Основные изменения |
|--------|------|-------------------|
| **1.2.0** | 2026-08-18 | Brain-бэкенды (Freebuff, Codebuff SDK), Security-фиксы, 1073 теста |
| **1.1.0** | 2026-08-17 | RiskScorer (5 уровней), BrainInterface, Context Engine, Voice, Modes |
| **1.0.0** | 2026-08-09 | Response Formatter, Personality, Model Fallback, OpenRouter |
| **1.0.0-beta** | 2026-08-06 | Web-чат, Desktop tools, Loop Guard, двухэтапный tool selection |
| **0.4.0** | 2026-07-30 | Версия 0.4.0 |
| **0.3.0** | 2026-07-30 | Notch UI, статус-логи, Ollama, Tavily |
| **0.2.0** | 2026-07-29 | Объединение FOL + SecondSelf, билингвальный routing |

---

## Главная философия

> **Для пользователя FOL выглядит как одна программа.**
> Он не думает: «Я сейчас использую Freebuff.»
> Он думает: «Я разговариваю с FOL.»
>
> Freebuff является внутренним Brain subsystem.
> FOL остаётся главным продуктом.

---

## Доступ к ресурсам

| Ресурс | URL |
|--------|-----|
| GitHub | `github.com/abdulakimabdimanapov-rgb/SecondSelf` |
| Orchestrator API | `http://localhost:8420` |
| Agent Server | `http://localhost:8421` |
| FOL API | `http://localhost:8754` |
| Web UI | `http://localhost:3000` |
| Freebuff | `freebuff.com` |
