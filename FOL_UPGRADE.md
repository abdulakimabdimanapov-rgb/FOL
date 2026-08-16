# FOL — Future of Life

## Мастер-документ архитектуры

> Когда новая модель заходит — она сразу понимает, что это за проект, куда он движется,
> и может немедленно приступить к работе.

---

## 1. ЧТО ЭТО ЗА ПРОЕКТ

**FOL** — это персональный AI-ассистент нового поколения, который:
- Живёт на **MacBook** как главный интеллект
- Работает как **Digital Twin** — цифровой двойник пользователя
- Контролирует **десктоп** (браузер, приложения, файлы)
- Имеет **Notch UI** (SwiftUI панель в вырезе MacBook)
- Понимает **контекст** экрана, почты, календаря
- Постоянно **в фоне** анализирует и предлагает действия
- Пишет в **память** (identity, preferences, episodic события)
- Использует **LLM** (Claude Sonnet 4 / Ollama локально)

**Текущее состояние:** Layers 1-5 работают. Layer 6 и Mobile Companion — в разработке.

---

## 2. АРХИТЕКТУРА СИСТЕМЫ (ТЕКУЩАЯ)

```
┌─────────────────────────────────────────────────────┐
│                  macOS (один компьютер)              │
│                                                     │
│  ┌──────────────────┐    ┌──────────────────────┐   │
│  │  UI Layer         │    │  Server Layer         │   │
│  │  SecondSelf.app   │◄──►│  Orchestrator :8420   │   │
│  │  (SwiftUI)        │SSE │  (FastAPI + Claude)   │   │
│  │  ┌─────────────┐  │    │  ┌────────────────┐  │   │
│  │  │ Notch Panel  │  │    │  │ Agent Loop     │  │   │
│  │  │ (NSPanel)    │  │    │  │ LLM + Tools    │  │   │
│  │  ├─────────────┤  │    │  ├────────────────┤  │   │
│  │  │ Chat View   │  │    │  │ Productivity   │  │   │
│  │  │ Messages    │  │    │  │ (Gmail, GCal)  │  │   │
│  │  │ A2UI Cards  │  │    │  ├────────────────┤  │   │
│  │  ├─────────────┤  │    │  │ Suggestion     │  │   │
│  │  │ VNC PiP     │  │    │  │ Engine         │  │   │
│  │  │ MJPEG       │  │    │  └────────────────┘  │   │
│  │  └─────────────┘  │    │  └────────────────┘  │   │
│  └──────────────────┘    └──────────┬───────────┘   │
│                                     │                │
│  ┌──────────────────────────────────┴────────────┐   │
│  │         Obsidian Vault (живая память)         │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐  │   │
│  │  │ Daily/   │ │ Profile/ │ │ Knowledge/   │  │   │
│  │  │ YYYY-MM  │ │ identity │ │ topics       │  │   │
│  │  ├──────────┤ ├──────────┤ ├──────────────┤  │   │
│  │  │ Episodic/│ │ Projects/│ │ Ideas/       │  │   │
│  │  │ events   │ │ ...      │ │ decisions    │  │   │
│  │  └──────────┘ └──────────┘ └──────────────┘  │   │
│  └──────────────────────────────────────────────┘   │
│                                     │                │
│  ┌──────────────────────────────────┴────────────┐   │
│  │           Agent Server :8421                   │   │
│  │  (Python HTTP Server — secondself session)     │   │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────────┐  │   │
│  │  │Desktop   │ │ Browser  │ │ Chrome CDP    │  │   │
│  │  │PyAutoGUI │ │ Control  │ │ :9222         │  │   │
│  │  └──────────┘ └──────────┘ └───────────────┘  │   │
│  └────────────────────────────────────────────────┘   │
│                                                     │
│  ┌──────────────────────────────────────────────┐    │
│  │          Identity Pipeline (main.py)          │   │
│  │  Gmail ─► Clean ─► Analyze ─► Build Profile  │   │
│  │  Tavily ─────────────────────┘               │   │
│  │  Calendar ──────────────────────────────────►│   │
│  │  Output: ~/.secondself/{identity,preferences, │   │
│  │          episodic}.md                         │   │
│  └──────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

### Ключевые компоненты

| Компонент | Технология | Роль |
|-----------|-----------|------|
| `orchestrator/server.py` | FastAPI + Anthropic SDK | LLM-маршрутизация, agentic loop, SSE |
| `agent-server/server.py` | Python HTTP Server | PyAutoGUI десктоп, browser CDP, MJPEG |
| `SecondSelf/` | SwiftUI + NSPanel | Notch UI, чат, A2UI рендеринг, VNC |
| `main.py` | Python CLI | Identity pipeline (Layers 1-4) |
| `src/auth/` | Auth0 / Firebase / Google OAuth | Аутентификация |
| `cookie_sync/` | Chrome CDP | Перенос сессий из Chrome → agent browser |

### Сеть портов

| Порт | Сервис | Сессия |
|------|--------|--------|
| 8420 | Orchestrator | Пользователь (primary) |
| 8421 | Agent Server | secondself (background) |
| 5901 | Vine VNC (резерв) | secondself |
| 9222 | Chrome DevTools | secondself |

---

## 3. СИСТЕМА ПАМЯТИ (6 LAYERS)

```
Layer 1: identity.md       — Кто ты (role, voice, interests, behavior)
Layer 2: preferences.md    — Как ты работаешь (schedule, tools, style)
Layer 2.5: relationships   — Кого ты знаешь (contact graph, closeness)
Layer 3: context_engine    — Контекстуальная память (активное приложение, URL)
Layer 4: episodic.md       — Что произошло (life events, actions) [→ Obsidian Episodic/events.md]
Layer 5: Obsidian Vault    — Семантическая память (Profile / Projects / Knowledge / Goals / Ideas / Tasks / Decisions / Daily)
Layer 6: procedural.md     — [PLAN] Процедурная память (навыки)
```

### Живая память (Living Memory)

Вся память автоматически **дублируется в Obsidian**:

| Источник | → Obsidian | Механизм |
|----------|------------|----------|
| `~/.secondself/identity.md` | `Profile/identity.md` | `sync_to_obsidian()` на старте |
| `~/.secondself/preferences.md` | `Profile/preferences.md` | `sync_to_obsidian()` на старте |
| `~/.secondself/episodic.md` | `Episodic/events.md` | `_sync_to_obsidian()` при каждом append (debounce 30s) |
| `utils/daily_tracker` | `Daily/YYYY-MM-DD.md` | `log_activity()` → `log_to_daily()` |
| `obsidian/tools: save_to_obsidian` | `Knowledge/*`, `Ideas/*`, `Projects/*` | LLM инструменты + `auto_link_note()` |
| `obsidian/tools: learn_from_web` | `Knowledge/*` | Tavily + LLM summary + auto-link |

**Semantic Linker:** после каждой записи запускается LLM, который извлекает ключевые concept'ы, ищет связанные заметки и добавляет `[[wikilinks]]` — и в исходную заметку, и обратные связи в найденные.

Файлы хранятся в `~/.secondself/` и автоматически подгружаются в system prompt при каждом запросе.

---

## 4. ИДЕИ FOL UPGRADE (ПЛАН РАЗВИТИЯ)

### 4.1 Dynamic Island
**Статус:** ✅ Реализован (Notch Panel SwiftUI)
**Что есть:** NSPanel с 4 состояниями (idle → peek → expanded → fullChat)
**Что нужно:** Улучшить анимации, добавить Task Status Bar, Progress Bar

### 4.2 Mobile Companion (iOS)
**Статус:** 🚧 План
**Что нужно:** Нативное iOS приложение с тем же Dynamic Island
**Архитектура:** Phone = интерфейс, MacBook = интеллект

### 4.3 Общая память (Obsidian)
**Статус:** ✅ Реализован
**Что сделано:**
- Obsidian vault как долговременная память
- read_note / write_note / search / patch_note через Local REST API
- init_vault — авто-создание структуры папок
- Semantic Linker — LLM-генерация [[wikilinks]] между заметками
- sync — двусторонняя синхронизация ~/.secondself/ ↔ Obsidian
- daily.py — ежедневные заметки с авто-логированием активности
- Живая память — все записи дублируются в Obsidian

**Структура Vault:**
```
Profile/          — identity.md, preferences.md, relationships.md
Projects/         — проекты с _index.md
Knowledge/        — знания и темы (авто-создаются из learn_from_web)
Goals/            — цели и roadmap
Ideas/            — банк идей с датой
Tasks/            — задачи (active, backlog, completed)
Decisions/        — архитектурные решения
Conversations/    — важные диалоги
Daily/            — ежедневные заметки (авто)
Episodic/         — события (sync из episodic.md)
Archive/          — завершённые проекты
```

### 4.4 Один интеллект
**Статус:** ✅ Реализован
**Логика:** LLM запускается ТОЛЬКО на MacBook. Телефон — интерфейс.

### 4.5 Bridge System
**Статус:** 🚧 План
**Что нужно:**
- WebSocket bridge Mac ↔ iPhone
- Передача запросов и ответов
- Синхронизация памяти
- Push-уведомления
- Продолжение задач между устройствами

### 4.6 Постоянная работа
**Статус:** ✅ Реализован
**Что есть:**
- Ambient loop в orchestrator (30s tick) — suggestions
- Daily heartbeat — авто-запись "User active on YYYY-MM-DD"
- Мониторинг активного приложения через `context_engine/app_monitor.py`
- Автоматическое отслеживание контекста (app + URL)
- Фоновый процесс через LaunchAgent
- Ежедневный auto-logging в Obsidian Daily note

### 4.7 Контекст экрана
**Статус:** ✅ Реализован
**Что сделано:**
- `context_engine/app_monitor.py` — активное приложение через AppleScript
- `context_engine/browser_url.py` — URL из Chrome/Safari/Arc
- `context_engine/snapshot.py` — объединённый ContextSnapshot + категоризация
- `build_context_messages()` — инжектит контекст в КАЖДЫЙ запрос к LLM
- Активное приложение + URL + категория → в system prompt

**Определяемые контексты:**
- VS Code / Xcode → Coding
- Google Chrome / Safari / Arc → Browsing (с URL)
- Terminal / iTerm2 → Terminal (с командой)
- Obsidian → Writing (с заметкой)

### 4.8 Голосовой помощник
**Статус:** ✅ Частично
**Что есть:** ElevenLabs STT, AudioRecorder, SpeechService
**Что нужно:** 
- Полноценный Voice Engine
- TTS (текст → речь, ElevenLabs или локально)
- Фоновый режим
- Естественный диалог

### 4.9 Команда AI-агентов
**Статус:** 🚧 План
**Что нужно:** Специализированные агенты:
| Агент | Роль |
|-------|------|
| Architect Agent | Проектирование архитектуры |
| Coding Agent | Написание кода |
| Review Agent | Code review |
| Research Agent | Исследование |
| Documentation Agent | Документация |
| Memory Agent | Управление памятью |
| Planning Agent | Планирование |
| Automation Agent | Автоматизация |

### 4.10 Plugin System
**Статус:** 🚧 План
**Модули (навыки):**
- GitHub
- VS Code
- Docker
- Telegram
- Browser (уже есть)
- Calendar (уже есть Gmail/Google Calendar)
- Notes
- Obsidian
- YouTube

### 4.11 Автоматизация
**Статус:** ✅ Частично
**Что есть:** Desktop tools (click, type, hotkey, open_app), Browser tools
**Что нужно:** 
- Длинные цепочки действий
- Скрипты автоматизации
- Работа с файловой системой
- Терминальные команды

### 4.12 Самоанализ
**Статус:** 🚧 План
После каждой задачи FOL записывает:
- Что получилось
- Ошибки
- Что улучшить
- Чему научился

### 4.13 Живая память
**Статус:** ✅ Реализован
Семантическая память: связи между заметками в Obsidian.

**Механизм:**
1. После каждой записи в vault запускается `auto_link_note()`
2. Semantic Linker извлекает ключевые concept'ы через LLM
3. Ищет похожие заметки через `search()`
4. LLM решает типы связей (related / parent / implements / source / follow_up)
5. Добавляет `[[wikilinks]]` в заметку
6. Обновляет backlinks в связанных заметках

```
идея → проект → задача → решение → документация
           ↕           ↕           ↕
       Knowledge    Goals      Episodic
```

### 4.14 Режимы работы
**Статус:** 🚧 План
| Режим | Включённые инструменты |
|-------|----------------------|
| Development | VS Code, Terminal, GitHub, Docker |
| Study | Browser, PDF, Notes, Obsidian |
| Focus | Блокировка уведомлений, только текущая задача |
| Creative | Browser, Notes, YouTube |
| Research | Browser, Tavily, Calendar |
| Planning | Calendar, Notes, Obsidian, Tasks |

### 4.15 Личный Dashboard
**Статус:** 🚧 План
Панель состояния FOL:
- Текущая задача
- Состояние агентов
- CPU / RAM (системная нагрузка)
- История действий
- Журнал событий
- Активные проекты

### 4.16 Архитектура
**Статус:** ✅ Частично
**Требования:** Модульность, масштабируемость, независимость, тестируемость
**Текущее:** Модули в analyze/, fetch/, clean/ уже независимы
**Нужно:** Никакого монолитного кода для новых фич

### 4.17 Код
**Стандарты:**
- Type hints везде
- SOLID, DRY, KISS, Clean Architecture
- Сначала анализ архитектуры → потом код
- Большие задачи → разбить на этапы
- После каждого этапа → обновить документацию
- Ожидать подтверждения перед продолжением

---

## 5. СИСТЕМНЫЙ PROMPT (КАК РАБОТАЕТ ОБЩЕНИЕ С ПОЛЬЗОВАТЕЛЕМ)

```
POST /chat {"message": "..."}
  → SSE stream событий:
    - event: token     — текст ответа
    - event: tool_call — вызов инструмента
    - event: tool_result — результат
    - event: component — A2UI компонент (TaskApproval, Screenshot, и т.д.)
    - event: state     — состояние (thinking / working / complete / error)
    - event: suggestion — проактивное предложение
```

### System Prompt собирается из:
1. **identity.md** (Layer 1) — голос, стиль, поведение
2. **preferences.md** (Layer 2) — расписание, инструменты
3. **episodic.md** (Layer 4) — последние события
4. **rules.md** (код) — правила использования инструментов

### Инструменты агента:
| Категория | Инструменты |
|-----------|------------|
| Browser | goto, click, fill, snapshot, text, press |
| Desktop | open_app, type_text, hotkey, click, screenshot, scroll |
| Productivity | send_email, draft_email, read_emails, create_event, search_web, etc. |
| UI | render_task_approval, render_profile_card, render_screenshot, render_confirm_action |

---

## 6. СТРУКТУРА ПРОЕКТА

```
/Users/USER/Desktop/SecondSelf/
├── FOL_UPGRADE.md               ← ВЫ ЗДЕСЬ
├── CLAUDE.md                     # Оригинальный контекст (Layer 1 pipeline)
├── README.md                     # Основное README
├── DESIGN.md                     # Дизайн-система
├── main.py                       # Identity pipeline CLI
├── requirements.txt              # Python зависимости
├── package.json / next.config    # Next.js (web onboarding)
│
├── SecondSelf/                   # SwiftUI macOS приложение
│   ├── SecondSelfApp.swift       # Entry point, AppDelegate
│   ├── NotchOverlayController.swift  # Notch управление
│   ├── NotchPanel.swift          # NSPanel (кастомный, без DynamicNotchKit)
│   ├── ViewModels/
│   │   └── ChatViewModel.swift   # SSE, сообщения, TwinState
│   ├── Views/                    # Все SwiftUI вьюхи
│   ├── Models/                   # ChatMessage, A2UI, SSE, TwinState
│   ├── Services/                 # Audio, ElevenLabs, Speech
│   ├── Auth/                     # GoogleAuthManager
│   └── Utilities/                # DesignTokens, AudioManager
│
├── orchestrator/                 # FastAPI сервер (главный интеллект)
│   ├── server.py                 # LLM bridge, SSE, tool dispatch
│   ├── productivity_tools.py     # Gmail, Calendar инструменты
│   ├── suggestion_engine.py      # Проактивные подсказки
│   ├── test_server.py            # Тесты
│   └── requirements.txt
│
├── agent-server/                 # Python HTTP сервер (десктоп контроль)
│   ├── server.py                 # PyAutoGUI, MJPEG, Chrome CDP
│   ├── screenshot.py             # Quartz скриншоты
│   └── requirements.txt
│
├── src/                          # Web backend (Next.js + Python)
│   ├── server.py                 # FastAPI onboarding сервер
│   ├── agent/                    # Chat handler, tool definitions
│   ├── connectors/               # Gmail, Calendar, Tavily
│   ├── auth/                     # Auth0, Firebase, Token store
│   ├── db/                       # Firestore repositories
│   ├── models/                   # Pydantic схемы
│   ├── synthesis/                # Deep profile pipeline
│   ├── app/                      # Next.js pages
│   ├── components/               # React компоненты
│   └── hooks/                    # React хуки
│
├── auth/                         # Python auth модули
│   ├── web_oauth.py              # FastAPI OAuth сервер
│   ├── gmail_auth.py             # Gmail credentials
│   └── ...
├── fetch/                        # Python fetch модули
│   ├── gmail_fetch.py            # Gmail API
│   ├── tavily_fetch.py           # Web search
│   └── calendar_fetch.py         # Google Calendar
├── clean/
│   └── email_cleaner.py          # HTML -> plain text
├── analyze/                      # LLM анализ (Identity Pipeline)
│   ├── voice_analyzer.py         # Стиль письма
│   ├── topic_extractor.py        # Темы
│   ├── behavior_analyzer.py      # Паттерны поведения
│   ├── relationship_mapper.py    # Контакты
│   ├── tavily_synthesizer.py     # Публичный профиль
│   ├── event_extractor.py        # Life events
│   └── _llm.py / _llm_async.py  # LLM вызовы
├── utils/
│   ├── episodic_writer.py        # Запись событий с файловой блокировкой
│   └── daily_tracker.py          # Ежедневный трекинг активности
├── context_engine/               # Контекст экрана (L3)
│   ├── app_monitor.py            # Активное приложение (AppleScript)
│   ├── browser_url.py            # URL из браузера (AppleScript)
│   └── snapshot.py               # Объединённый ContextSnapshot
├── obsidian/                     # Obsidian Memory Bridge (L5)
│   ├── __init__.py
│   ├── config.py                 # Настройки подключения
│   ├── client.py                 # HTTP клиент к Local REST API
│   ├── vault.py                  # CRUD + структура папок
│   ├── daily.py                  # Ежедневные заметки
│   ├── linker.py                 # Semantic Linker
│   ├── sync.py                   # Sync ~/.secondself/ ↔ Obsidian
│   └── tools.py                  # LLM-инструменты (learn_from_web, save_to_obsidian)
├── cookie_sync/                  # Cookie перенос Chrome → agent browser
├── setup/                        # LaunchAgent скрипты
├── tests/                        # Python тесты (430+)
└── docs/
    └── SPEC-agent-browser-integration.md
```

---

## 7. ПЛАН РАЗВИТИЯ (ROADMAP)

### Фаза 1: Dynamic Island + Core ✅
- [x] Notch SwiftUI панель
- [x] 4 состояния (idle/peek/expanded/fullChat)
- [x] Чат с LLM через SSE
- [x] A2UI компоненты (TaskApproval, Screenshot, ConfirmAction)
- [x] Desktop tools (PyAutoGUI)
- [x] Browser tools (Chrome CDP)

### Фаза 2: Identity Pipeline ✅
- [x] Gmail OAuth + fetch
- [x] Tavily web search
- [x] Voice / Topic / Behavior / Relationship анализ
- [x] identity.md, preferences.md, episodic.md
- [x] Event extraction (life events)

### Фаза 3: Проактивность + Память ✅
- [x] Suggestion Engine (profile_trigger / pattern_trigger / ambient_tick)
- [x] Screen context detection (context_engine/: app_monitor + browser_url + snapshot)
- [x] Always-on режим (LaunchAgent + ambient loop в lifespan)
- [x] Ambient loop → рабочая петля (30s tick, suggestions broadcast)
- [x] Самоанализ после задач (_log_episodic_event в agent loop)
- [x] Memory persistence fix (build_context_messages() инжектится в каждый LLM запрос)
- [x] Daily tracking (utils/daily_tracker + heartbeat)

### Фаза 4: Multi-Agent System 🚧
- [ ] Architect Agent
- [ ] Coding Agent
- [ ] Review Agent
- [ ] Research Agent
- [ ] Documentation Agent
- [ ] Memory Agent
- [ ] Planning Agent
- [ ] Automation Agent

### Фаза 5: Bridge + Mobile 🚧
- [ ] WebSocket bridge (Mac ↔ iPhone)
- [ ] iOS приложение (интерфейс)
- [ ] Синхронизация памяти
- [ ] Push-уведомления
- [ ] Продолжение задач

### Фаза 6: Obsidian Living Memory ✅
- [x] Obsidian HTTP client (read_note / write_note / search / patch_note)
- [x] Vault manager (init_vault, save_note с авто-линковкой)
- [x] Daily notes (ensure_daily_note, log_to_daily, log_app_usage)
- [x] Semantic Linker (auto_link_note — извлечение concepts → поиск → [[wikilinks]] → backlinks)
- [x] Sync ~/.secondself/ ↔ Obsidian (identity, preferences, episodic)
- [x] LLM tools (learn_from_web, save_to_obsidian, get_daily_summary)
- [x] Episodic writer дублирует в Obsidian Episodic/events.md
- [x] Daily tracker пишет в Obsidian Daily/YYYY-MM-DD.md
- [x] auto_link=True по умолчанию для всех save_note

### Фаза 7: Plugin System + Modes 🚧
- [ ] Plugin SDK
- [ ] GitHub connector
- [ ] VS Code connector
- [ ] Режимы работы (Development / Study / Focus / Creative / Research / Planning)
- [ ] Personal Dashboard

### Фаза 8: Voice + Automation 🚧
- [ ] Полный Voice Engine (STT + TTS)
- [ ] Фоновый голосовой ассистент
- [ ] Длинные цепочки действий
- [ ] Скрипты автоматизации

---

## 8. ПРИНЦИПЫ РАБОТЫ ДЛЯ НОВОЙ МОДЕЛИ

Когда ты, новая модель, заходишь в этот проект:

1. **Прочитай FOL_UPGRADE.md** — ты уже здесь, и это правильно.
2. **Прочитай README.md** — общее понимание системы.
3. **Прочитай CLAUDE.md** — детали Identity Pipeline.
4. **Прочитай DESIGN.md** — дизайн-система (цвета, шрифты, анимации).
5. **Прочитай `orchestrator/server.py`** — главный файл: LLM + tool loop + SSE.
6. **Посмотри `SecondSelf/`** — SwiftUI UI слой.

### Что важно:
- **Не переписывай работающий код.** Только добавляй новый или рефактори.
- **SOLID, DRY, KISS.** Код уровня Senior Engineer.
- **Type hints.** Везде.
- **Модульность.** Каждый модуль независим и тестируем.
- **Сначала архитектура → потом код.** Не прыгай в реализацию без плана.
- **Большие задачи → разбить на этапы.** Каждый этап → подтверждение.
- **Документируй.** Обновляй CLAUDE.md / FOL_UPGRADE.md после значимых изменений.

### Контекст при запуске:
- Orchestrator запускается на `localhost:8420`
- Agent Server на `localhost:8421` (в фоновой сессии secondself)
- SwiftUI приложение подключается через SSE к `localhost:8420/events`
- Chat идёт через `POST /chat` → SSE stream
- Memory файлы: `~/.secondself/{identity,preferences,episodic}.md`
- .env: `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `GOOGLE_*`, `FIREBASE_*`

### Если надо запустить:
```bash
# Identity Pipeline
python main.py

# SwiftUI приложение
cd SecondSelf && swift build && swift run

# Отдельно сервера
python orchestrator/server.py     # :8420
python agent-server/server.py     # :8421
```

### Если надо протестировать:
```bash
python -m pytest tests/ -v        # Python тесты
python orchestrator/test_server.py   # Тесты orchestatora
```

---

## 9. КЛЮЧЕВЫЕ РЕШЕНИЯ

| Дата | Решение | Причина |
|------|---------|---------|
| 2026-03 | DynamicNotchKit → кастомный NSPanel | Убрали зависимость, Swift 6 совместимость |
| 2026-03 | Ollama как fallback модель | Локальный режим без API ключей |
| 2026-03 | Obsidian как долговременная память | Markdown-native, связи между заметками |
| 2026-03 | Один интеллект на MacBook | Телефон только интерфейс |
| 2026-03 | A2UI протокол для UI компонентов | Структурированные карточки вместо текста |
| 2026-03 | Cookie sync через Chrome CDP | Безопасный перенос сессий |
| 2026-03 | 6-layer memory system | Многоуровневая память от identity до процедурной |
| 2026-04 | Screen context detection (context_engine/) | AppleScript-мониторинг активного приложения + URL |
| 2026-04 | Memory persistence fix (build_context_messages) | Контекст инжектится в КАЖДЫЙ запрос к LLM |
| 2026-04 | Obsidian как живая память (Layer 5) | Obsidian Local REST API + Semantic Linker + daily notes |
| 2026-04 | Daily auto-logging в Obsidian | Activity tracker → Daily/YYYY-MM-DD.md + Episodic/events.md |

---

*FOL — Future of Life. Личный AI-ассистент нового поколения.*
*Центральная интеллектуальная система пользователя на MacBook и телефоне.*
*Единый помощник, который никогда не выключается.*
