# 📖 FOL — Алфавитный справочник проекта

> Полное описание проекта FOL в виде алфавитного указателя.
> Здесь собраны **все** компоненты, сервисы, порты, агенты, модели,
> команды и технологии — от A до Z.
>
> **Версия проекта:** v1.0.0 · **Статус:** стабильный релиз (2026-08-09)
> **Тесты:** 989+ корневых + 438 FOL · **Лицензия:** MIT

---

## Содержание

- [Общее описание проекта](#общее-описание)
- [Алфавитный указатель A–Z](#алфавитный-указатель)
- [Сводные таблицы](#сводные-таблицы)
  - [Порты и сервисы](#порты-и-сервисы)
  - [Агенты роутера](#агенты-роутера)
  - [LLM-модели](#llm-модели)
  - [Память (6 слоёв)](#память-6-слоёв)
  - [Основные команды](#основные-команды)
  - [Переменные окружения (.env)](#переменные-окружения-env)

---

## Общее описание

**FOL (Friendly Obedient Listener / Future of Life)** — персональный
AI-ассистент уровня JARVIS, цифровой двойник пользователя на macOS.

| Параметр | Значение |
|---|---|
| **Что это** | AI-ассистент + digital twin, живёт на MacBook в Notch-панели |
| **Интерфейсы** | Notch UI (SwiftUI), Web (Next.js), Mobile PWA (bridge), CLI, голос |
| **Ядро** | Python 3.9+ (реком. 3.11), FastAPI, LiteLLM, SwiftUI |
| **Главные сервисы** | Orchestrator (:8420), Agent Server (:8421), Bridge (:8422), Dashboard (:8423), FOL API (:8754) |
| **LLM** | OpenRouter / OpenAI / Anthropic / Gemini (только API, без локальных моделей) с автопереключением |
| **Память** | 6 слоёв: identity → preferences → relationships → context → episodic → Obsidian vault |
| **Особенности** | Билингвальный роутер (RU+EN), двухэтапный выбор инструментов, loop guard, живая память Obsidian, голос, зрение, агентный цикл |

### Как устроен проект (архитектура)

```
Пользователь (Notch UI / Web / Phone / Голос)
      │
      ▼
Orchestrator (FastAPI, :8420)
      │  роутер агентов (General/Architect/Coder/Reviewer/Researcher/Memory)
      │  двухэтапный выбор инструментов (категория → 5–12)
      │  loop guard (защита от зацикливания)
      ▼
LLM (LiteLLM: OpenRouter / OpenAI / Anthropic / Gemini — cloud-only)
      │  tool calls
      ▼
Исполнение: Agent Server (:8421) · Productivity (Gmail/Calendar) · Obsidian · FOL (:8754)
      │
      ▼
Результат → LLM → финальный ответ (SSE-стриминг в UI)
```

---

## Алфавитный указатель

## A

### agent-server — Сервер десктоп-контроля
- **Путь:** `agent-server/server.py`, `agent-server/screenshot.py`
- **Порт:** 8421 · **Технология:** Python `http.server`, PyAutoGUI, AppleScript
- **Роль:** работает в фоновой сессии `secondself`; управляет десктопом и браузером: клики, ввод текста, горячие клавиши, скриншоты (MJPEG-поток), открытие/закрытие приложений, drag, буфер обмена, уведомления, Chrome CDP (:9222), Safari.
- **Инструменты:** `click`, `double_click`, `type_text`, `hotkey`, `open_app`, `close_app`, `drag`, `clipboard_get/set`, `notify`, `move_mouse`, `screenshot`, `browser_*`, `safari_*`

### agents — Агенты роутера
- **Путь:** `orchestrator/agents/` (architect.py, coder.py, reviewer.py, researcher.py, memory.py, router.py)
- **Роль:** 6 специализированных агентов + билингвальный роутер (см. [Агенты роутера](#агенты-роутера))

### analyze — Модуль анализа (Identity Pipeline)
- **Путь:** `analyze/`
- **Файлы:** `voice_analyzer.py` (стиль письма), `topic_extractor.py` (темы), `behavior_analyzer.py` (поведение), `relationship_mapper.py` (контакты), `tavily_synthesizer.py` (публичный профиль), `event_extractor.py` (жизненные события), `_llm.py` / `_llm_async.py` (LLM-адаптер с фолбэк-цепочкой)
- **Роль:** анализ почты/веба для построения профиля пользователя (слои 1–4)

### auth — Аутентификация
- **Путь:** `auth/web_oauth.py`, `auth/gmail_auth.py`
- **Роль:** Google OAuth для Gmail/Calendar, FastAPI OAuth-сервер

### A2UI — Протокол UI-компонентов
- **Роль:** структурированные карточки вместо текста: `render_task_approval`, `render_profile_card`, `render_screenshot`, `render_confirm_action`
- **Реализация:** SwiftUI (`A2UIRenderer.swift`, `TaskApprovalView.swift`, `ConfirmActionView.swift`, `ScreenshotPreviewCard.swift`, `ProfileCardView.swift`)
- **SSE-событие:** `component`

### Audio — Звук и голос (JARVIS)
- **Swift:** `fol-app/Utilities/AudioManager.swift`, `SoundSynthesizer.swift` — JARVIS-звуки синтезируются в памяти (активация, подтверждение, HUD-клики)
- **Файлы .wav:** `jarvis_activation.wav`, `jarvis_boot_chime.wav`, `jarvis_confirmation.wav`, `jarvis_hud_click.wav`
- **Запись голоса:** `fol-app/Services/AudioRecorder.swift`, `SpeechService.swift`, `ElevenLabsService.swift` (STT)

## B

### Bilingual routing — Билингвальный роутер
- **Путь:** `orchestrator/agents/router.py`
- **Роль:** маршрутизация команд на русском и английском (и mixed)
- **Алгоритм:** greeting → bilingual → exact keyword → fuzzy (typo-tolerant) → история → GENERAL
- **Фичи:** `_detect_language()`, `_bilingual_route()` (majority vote), `_fuzzy_classify()` (difflib, cutoff 0.72), `_is_greeting()` (word boundaries)

### bridge — Мост телефон ↔ Mac
- **Путь:** `bridge/server.py`, `bridge/static/` (PWA), `bridge/start.sh`
- **Порт:** 8422 (env `BRIDGE_PORT`)
- **Роль:** WebSocket-мост между телефоном и Orchestrator (:8420); отдаёт мобильный PWA (`index.html`, `manifest.json`); ответы санитизируются (`humanize_error`) — tool-calls никогда не уходят на телефон
- **Endpoints:** `GET /`, `GET /manifest.json`, `GET /health`, `WS /ws`

### Browser — Браузерные инструменты
- **Роль:** Chrome (`browser_navigate`, `browser_search`, `browser_click`, `browser_fill`…) через Chrome CDP (:9222) и Safari (`safari_goto`…)
- **Cookie sync:** `cookie_sync/` — перенос сессий из профиля Chrome в агент-браузер (с подтверждением пользователя)

### build-app.sh / build-pkg.sh — Сборка
- **Путь:** `build-app.sh` (сборка `.app`), `build-pkg.sh` (сборка `.pkg`), `build-pkg.sh` включает postinstall-скрипт
- **Подпись:** Developer ID при наличии, иначе ad-hoc codesign (`scripts/sign-and-notarize.sh`)

## C

### CHANGELOG.md — История версий
- **Путь:** `CHANGELOG.md` · **Формат:** Keep a Changelog, SemVer
- **История:** v0.2.0 → 0.3.0 → 0.4.0 → 1.0.0-beta → **1.0.0**

### CLAUDE.md — Контекст для AI-моделей
- **Путь:** `CLAUDE.md` · **Роль:** единая документация для моделей (роутер, нормализация, тесты, баги)

### clean — Очистка почты
- **Путь:** `clean/email_cleaner.py` · **Роль:** HTML → plain text для анализа

### Context Engine — Контекст экрана
- **Путь:** `context_engine/app_monitor.py` (активное приложение), `browser_url.py` (URL Chrome/Safari/Arc), `snapshot.py` (ContextSnapshot + категоризация)
- **Роль:** определяет контекст: VS Code/Xcode → Coding, Chrome/Safari/Arc → Browsing (+URL), Terminal → Terminal, Obsidian → Writing
- **Инжекция:** `build_context_messages()` — контекст в КАЖДЫЙ запрос к LLM

### cookie_sync — Перенос cookies
- **Путь:** `cookie_sync/sync.py`, `export.py`, `import_cookies.py`
- **Роль:** перенос сессий Chrome → агент-браузер через CDP (безопасно, с подтверждением)

## D

### Dashboard — Мониторинг системы
- **Путь:** `dashboard/server.py`, `dashboard/collector.py`, `dashboard/static/dashboard.html`
- **Порт:** 8423
- **Роль:** CPU, RAM, Disk, Network, статус Orchestrator, сервисы, топ-процессы, события episodic-памяти, активные проекты; live-обновление через WebSocket

### DESIGN.md — Дизайн-система
- **Путь:** `DESIGN.md` · **Роль:** цвета, шрифты, анимации (SwiftUI: `DesignTokens.swift`, `Assets.xcassets/Colors/`)

### Desktop tools — Десктоп-инструменты
- **Роль:** `open_app`, `close_app`, `type_text`, `hotkey`, `click`, `drag`, `screenshot`, `scroll`, `clipboard`, `notify` (PyAutoGUI + AppleScript)

### Docker / CI
- **Файлы:** `Dockerfile`, `docker-compose.yml` (backend API :8000), `.github/workflows/test.yml` (pytest + syntax + Swift build), `render.yaml`, `nixpacks.toml`, `Procfile` (uvicorn src.server:app)

## E

### ElevenLabs — STT (голос → текст)
- **Путь:** `fol-app/Services/ElevenLabsService.swift`
- **Роль:** распознавание речи при удержании кнопки (hold-to-talk STT)

### episodic — Эпизодическая память
- **Путь:** `utils/episodic_writer.py` (запись с файловой блокировкой), `orchestrator/output/episodic.md`
- **Роль:** слой 4 — жизненные события; дублируется в Obsidian `Episodic/events.md` (debounce 30s)

### .env — Конфигурация
- **Файлы:** `.env` (не в Git), `.env.example`, `.env.template`, `fol-app/.env.template`
- **Роль:** все ключи и настройки (см. [Переменные окружения](#переменные-окружения-env))

## F

### fetch — Получение данных
- **Путь:** `fetch/gmail_fetch.py`, `fetch/tavily_fetch.py`, `fetch/calendar_fetch.py`
- **Роль:** Gmail API, веб-поиск Tavily, Google Calendar

### FOL — Ядро (Python AI)
- **Путь:** `fol/` · **Порт:** 8754
- **Роль:** каноническое ядро FOL: `core/` (app, pipeline, orchestrator, event_bus, lifecycle, task_manager, context_manager), `modules/` (llm, memory, tools, input, output, plugins), `api/` (REST + WebSocket), `config/`, `ui/` (web + macos)
- **Запуск:** `python fol/run_api_server.py` (REST :8754), `python fol/fol_mac_app.py` (PyObjC notch-окно), `python fol/main.py` (CLI), `fol/run_fol_macos.sh`
- **Версия ядра:** 2.0.0 (в `fol/core/app.py`)

### FOL_UPGRADE.md — Мастер-документ
- **Путь:** `FOL_UPGRADE.md` · **Роль:** полный план развития проекта, архитектура, память, ключевые решения

### FOL API — REST + WebSocket
- **Путь:** `fol/api/rest/server.py` + routes (`conversation`, `memory`, `tools`, `settings`, `plugins`), `fol/api/websocket/`
- **Endpoints:** `GET /health`, `POST /conversation/send`, `GET /tools/`, `POST /tools/{name}/execute`, `WS /ws`, `GET /docs`

## G

### Gmail — Почта
- **Путь:** `fetch/gmail_fetch.py`, `auth/gmail_auth.py`, `clean/email_cleaner.py`
- **Инструменты:** `send_email`, `draft_email`, `read_emails`, сводки, контакты

### Google Calendar — Календарь
- **Путь:** `fetch/calendar_fetch.py` · **Инструмент:** `create_event`

## H

### Health checks — Проверка сервисов
- **Endpoints:** `GET /health` в orchestrator (:8420), agent-server (:8421), bridge (:8422), dashboard (:8423), FOL API (:8754), src (:8000)
- **Скрипты:** `setup/smoke-test.sh`, `scripts/e2e_check.py` (запускает все 3 сервиса и проверяет health, MJPEG, SSE-чат)

## I

### Identity Pipeline — Построение профиля
- **Путь:** `main.py` (CLI)
- **Поток:** Auth (Google OAuth) → Gmail fetch → clean → analyze (voice/topic/behavior/relationships) → Tavily → Calendar → Build → Output `~/.secondself/{identity, preferences, episodic}.md`
- **Слои 1–4:** identity.md (кто ты), preferences.md (как работаешь), relationships (кого знаешь), episodic.md (что произошло)

### Info.plist — Конфигурация приложения
- **Пути:** `fol-app/Info.plist`, `fol/ui/macos/Resources/Info.plist`
- **Роль:** CFBundleName = FOL, разрешения (микрофон, accessibility, AppleEvents)

## J

### JARVIS — Голосовые эффекты и речь
- **Роль:** синтезированные звуки интерфейса (активация, подтверждение, HUD-клики), TTS через `say`, прерывание речи при вводе (interrupt speaking)

## L

### LLM — Языковые модели
- **Путь:** `analyze/_llm.py`, `analyze/_llm_async.py`, `orchestrator/llm_bridge.py`, `fol/modules/llm/` (router.py, engine.py, backends/, personality.py)
- **Провайдеры:** OpenRouter (по умолчанию), OpenAI, Anthropic, Gemini — только API-провайдеры; локальные LLM (Ollama/MLX) исключены политикой
- **Фолбэк:** `LLM_FALLBACK_MODELS` — цепочка моделей, пустой ответ = сбой → следующая модель; модели без ключа пропускаются
- **См.** [LLM-модели](#llm-модели)

### llm_bridge — Единый LLM-мост
- **Путь:** `orchestrator/llm_bridge.py`
- **Роль:** канонический мост LLM-вызовов (Phase 6): `llm_call`, `llm_call_json`, `llm_acompletion`, `llm_astream`, `llm_completion_sync`

### Loop guard — Защита от зацикливания
- **Роль:** повторный вызов одного инструмента N раз подряд (`MAX_REPEATED_TOOL_CALLS`) прерывается; история закрывается валидными `tool_result`

## M

### main.py — Identity Pipeline CLI
- **Путь:** `main.py` · **Роль:** запуск полного пайплайна профиля (слои 1–4), `--no-cache`, `--dry-run`

### Memory — Память (6 слоёв)
- **См.** [Память (6 слоёв)](#память-6-слоёв)
- **Пути:** `~/.secondself/`, `utils/episodic_writer.py`, `utils/daily_tracker.py`, `obsidian/`, `orchestrator/memory_bridge.py`, `fol/modules/memory/`

### MERGED_README.md — Документация слияния
- **Путь:** `MERGED_README.md` · **Роль:** полная документация объединения FOL + SecondSelf

### MJPEG — Видеопоток экрана
- **Роль:** живой поток экрана агент-сессии (`/viewer` в agent-server, `VNCPipView.swift` в SwiftUI)

## N

### Next.js — Web-интерфейс
- **Путь:** `src/` (app/, components/, hooks/), `package.json`
- **Стек:** Next.js 16, React 19, Tailwind 4, TypeScript 5.9
- **Чат:** `POST /api/chat/stream` → orchestrator :8420 → SSE-стриминг токенов, tool-call пилюли, состояния thinking/working/complete
- **Порт:** 3000 (dev)

### normalize_user_input — Нормализация текста
- **Путь:** `orchestrator/server.py`
- **Роль:** очистка whitespace, каппинг повторов, 22 русские аббревиатуры (спс→спасибо…), фонетические подстановки (`_RU_TYPO_MAP`)

### Notch UI — Панель в вырезе MacBook
- **Путь:** `fol-app/` (NotchPanel.swift, NotchOverlayController.swift, NotchViews.swift, ChatView.swift…), `fol/ui/macos/Sources/SecondSelf/`
- **Роль:** NSPanel с 4 состояниями (idle → peek → expanded → fullChat), A2UI-карточки, VNC PiP, голосовая кнопка

## O

### obsidian — Живая память (Obsidian Brain v5)
- **Путь:** `obsidian/client.py` (Local REST API 5.0.2), `vault.py` (CRUD + init_vault + refresh_indices), `linker.py` (Semantic Linker — `[[wikilinks]]`), `sync.py` (двусторонняя синхронизация), `daily.py` (ежедневные заметки), `tools.py` (`save_to_obsidian`, `learn_from_web`, `get_daily_summary`), `config.py`
- **Vault-структура:** Profile / Projects / Knowledge / Goals / Ideas / Tasks / Decisions / Conversations / Daily / Episodic / Archive / Templates
- **Инструменты LLM:** `save_to_obsidian` (Knowledge/*, Ideas/*, Projects/*), `learn_from_web` (Tavily + LLM + auto-link)

### orchestrator — Главный AI-сервер
- **Путь:** `orchestrator/server.py`
- **Порт:** 8420
- **Роль:** FastAPI: `/chat` (SSE), `/events`, `/command`, `/suggestions`, `/health`; агентный цикл (LLM + tool calls), двухэтапный выбор инструментов, loop guard, роутер агентов
- **Файлы:** `tool_registry.py`, `tool_handlers.py`, `productivity_tools.py`, `suggestion_engine.py`, `llm_bridge.py`, `agent_transport.py`, `memory_bridge.py`, `response_formatter.py`, `applescript_apps.py`

### orchestrator/agents — см. [agents](#agents)

## P

### personality.py — Личность ответов
- **Путь:** `fol/modules/llm/personality.py`
- **Роль:** JARVIS-стиль, лёгкий юмор, язык пользователя; вырезает JSON/XML tool-calls из финальных ответов; `polish_response`, `contextual_confirmation`, `is_terse_response`

### Plugins — Плагины FOL
- **Путь:** `fol/modules/plugins/` (manager, loader, hooks, api, base) + `fol/plugins/example_plugin/`
- **Роль:** загрузка/выгрузка плагинов в рантайме, event hooks (on_input, before_llm, after_llm), кастомные инструменты

### Productivity tools — Инструменты продуктивности
- **Путь:** `orchestrator/productivity_tools.py`
- **Роль:** Gmail (send/draft/read), Google Calendar (create_event), Docs, веб-поиск Tavily

### Ports — Порты (см. [таблицу](#порты-и-сервисы))

## R

### README.md — Основная документация
- **Путь:** `README.md` · **Роль:** быстрый старт, сценарии, архитектура, структура, качество

### RELEASE_NOTES.md — Заметки релиза
- **Путь:** `RELEASE_NOTES.md` · **Роль:** v1.0.0: системные требования, что нового, чек-лист, установка, порты

### Researcher — Агент-исследователь
- **Ключевые слова:** EN: search, find, what is, explain · RU: найд, поищ, ищи, гугл
- **Роль:** веб-исследования через Tavily + синтез

### Response Formatter — Санитизация ответов
- **Путь:** `orchestrator/response_formatter.py`
- **Роль:** инструменты, JSON и имена tool-ов никогда не попадают в чат; SSE-тип `activity` (category + label); `humanize_error()`

### ROADMAP.md — План развития
- **Путь:** `ROADMAP.md` · **Роль:** идеи v2.0+ (Plugin SDK, Knowledge Graph, Mobile Companion, Cloud Sync, Workflow Builder)

### router.py — см. [Bilingual routing](#bilingual-routing)

### run_all.sh — Единый лаунчер
- **Путь:** `run_all.sh`
- **Команды:** `./run_all.sh` (все), `orchestrator`, `agent`, `fol`, `swift`; сам проверяет и убивает процессы на портах

## S

### scripts — Скрипты
- **Путь:** `scripts/`
- **Ключевые:** `demo.sh` (видео-демо), `verify_scenarios.sh` (5 сценариев), `e2e_check.py`, `e2e_final_response.py`, `run_benchmarks.sh`, `compare_benchmarks.py`, `stress_test_nemotron.py`, `verify_nemotron.py`, `sign-and-notarize.sh`, `vendor-deps.sh`, `fetch-python.sh`, `make_readme_pdf.py`, `start_services.py`

### FOL — SwiftUI macOS приложение
- **Путь:** `fol-app/`
- **Структура:** ViewModels/ (ChatViewModel), Views/ (ChatView, ChatInputBar, VoiceInputButton, A2UIRenderer, VNCPipView, SetupWizardView…), Models/ (ChatMessage, A2UIModels, TwinState…), Services/ (Audio, Speech, ElevenLabs, MultipartFormData), Utilities/ (DesignTokens, AudioManager, SoundSynthesizer)
- **Роль:** Notch UI, SSE-чат, голос, A2UI-карточки, VNC PiP, меню-бар (status item), проверка/запуск сервисов (не убивает живые)

### setup — Установка и LaunchAgent
- **Путь:** `setup/`
- **Файлы:** `setup-secondself.sh`, `provision.sh`, `smoke-test.sh`, `restart-agent.sh`, `update-agent-server.sh`, `debug-vnc.sh`, `test-agent.sh`, `setup-obsidian.sh`, plist'ы: `ai.secondself.agent.plist`, `ai.secondself.orchestrator.plist`, `ai.secondself.vine.plist`, `ai.secondself.chrome.plist`

### src — Web-бэкенд (Next.js + Python)
- **Путь:** `src/`
- **Структура:** `server.py` (FastAPI :8000, local AI mode), `agent/` (chat.py, tools.py, tool_defs.py), `auth/` (auth0_oauth.py, firebase_oauth.py, token_store.py), `connectors/` (gmail.py, calendar.py, tavily.py), `db/` (Firestore repositories: session, profile, chat, episodic), `models/` (schemas.py), `synthesis/` (profile.py, deep_profile.py), `app/` (Next.js: chat, onboard, wizard), `components/` (wizard, chat, mascot), `lib/` (firebase.ts, api.ts)
- **Порт:** 8000 (backend), 3000 (Next.js)

### SSE — Server-Sent Events (стриминг)
- **События:** `token`, `tool_call`, `tool_result`, `component` (A2UI), `state` (thinking/working/complete/error), `suggestion`, `activity`
- **Роль:** живой чат в реальном времени (macOS + web + bridge)

### Suggestion Engine — Проактивные подсказки
- **Путь:** `orchestrator/suggestion_engine.py`
- **Роль:** триггеры: profile_trigger / pattern_trigger / ambient_tick (30s loop)

## T

### Tavily — Веб-поиск
- **Путь:** `fetch/tavily_fetch.py`, `analyze/tavily_synthesizer.py`, `src/connectors/tavily.py`
- **Роль:** поиск в интернете, синтез публичного профиля, `search_web` инструмент

### tests — Тесты
- **Путь:** `tests/` (корневые) + `fol/tests/` (ядро)
- **Количество:** 989+ корневых + 438 FOL
- **Покрытие:** роутер (213), нормализация (48), память, инструменты, SSE, фолбэк моделей, response formatter, personality, obsidian v5, shell-command extraction (39), контекст-разговор (46), режимы (36)
- **Запуск:** `python3 -m pytest tests/ -v`, `pytest.ini` (-n auto, --tb=short)

### Tools — Инструменты (реестр)
- **Пути:** `orchestrator/tool_registry.py`, `orchestrator/tool_handlers.py`, `fol/modules/tools/` (registry.py, base.py — ToolSpec, gate.py), `fol/modules/tools/system/`, `desktop/`, `browser/`, `mouse_keyboard/`, `automation/`
- **ToolSpec:** name, description, schema, risk_level (low/medium/high/critical), requires_confirmation, execution
- **Двухэтапный выбор:** категория задачи (email/calendar/docs/memory/web/coding/desktop) → 5–12 релевантных инструментов вместо 50

### Tool call extraction — Извлечение команд
- **Путь:** `fol/core/app.py` — `_extract_shell_command()`: самый длинный префикс первым, снятие мусора («пожалуйста», пунктуация)

## U

### utils — Утилиты
- **Путь:** `utils/`
- **Файлы:** `episodic_writer.py`, `daily_tracker.py` (ежедневный трекинг + Obsidian Daily/YYYY-MM-DD.md), `text_normalizer.py`

## V

### VERSION — Файл версии
- **Путь:** `VERSION` · **Значение:** 1.0.0

### VNC — Виртуальный дисплей
- **Путь:** `setup/ai.secondself.vine.plist` · **Порт:** 5901 (резервный VNC, сессия secondself)
- **Роль:** PiP-просмотр экрана агент-сессии (`VNCPipView.swift`)

### Voice — Голосовой ввод
- **Путь:** `fol-app/Views/VoiceInputButton.swift` (анимация пульсации, pulse rings, glow), `fol-app/Views/ChatInputBar.swift` (AudioWaveformView — физическая симуляция волн: масса-пружина-демпфер)
- **Роль:** hold-to-talk запись, состояния idle/recording/transcribing/error

## W

### Web UI — Веб-интерфейсы
- **Пути:** Next.js (`src/app/`), bridge PWA (`bridge/static/index.html`), FOL web UI (`fol/ui/web/index.html`), dashboard (`dashboard/static/dashboard.html`), login (`src/static/login.html`, `static/login.html`)

### WebSocket — Реалтайм
- **Пути:** `bridge/server.py` (`WS /ws`), `dashboard/server.py` (live metrics), `fol/api/websocket/`

---

## Сводные таблицы

### Порты и сервисы

| Порт | Сервис | Описание |
|------|--------|----------|
| **8420** | Orchestrator | Главный AI-сервер: `/chat` (SSE), агентный цикл, роутер |
| **8421** | Agent Server | Десктоп/браузер контроль (PyAutoGUI, MJPEG, CDP) |
| **8422** | Bridge | WebSocket-мост телефон ↔ Mac (PWA) |
| **8423** | Dashboard | Мониторинг системы (CPU/RAM/сеть/сервисы) |
| **8754** | FOL API | JARVIS-команды, REST + WebSocket, `/docs` |
| **8000** | Backend API (Docker/Render) | `src.server:app` |
| **3000** | Next.js | Web-интерфейс (dev) |
| **9222** | Chrome DevTools | Агент-браузер (CDP) |
| **5901** | Vine VNC (резерв) | Виртуальный дисплей secondself |
| ~~11434~~ | ~~Ollama~~ | Удалён политикой «без локальных LLM» |

### Агенты роутера

| Агент | Ключевые слова EN | Ключевые слова RU | Роль |
|-------|-------------------|-------------------|------|
| **Architect** | architecture, design pattern, system design, roadmap | архитектур, спроектир, схема, тз | Проектирование архитектуры |
| **Reviewer** | review, check, code review, audit, vulnerability | провер, ревью, качеств, аудит | Code review (приоритет ПЕРЕД Coder) |
| **Coder** | implement, write code, pull request, refactor | напиш, код, создай, баг, тест | Написание кода |
| **Researcher** | search, find, what is, explain | найд, поищ, ищи, гугл | Исследование (Tavily) |
| **Memory** | remember, save, note, obsidian, remind | запомн, сохран, заметк, напомн | Управление памятью (Obsidian) |
| **General** | — (fallback) | — (fallback) | Обычный диалог, приветствия |

### LLM-модели

| Модель | Провайдер | Использование |
|--------|-----------|---------------|
| `openrouter/nvidia/nemotron-3-super-120b-a12b:free` | OpenRouter | **По умолчанию** (бесплатно, отличный tool calling) |
| `openai/gpt-4o-mini` | OpenAI | Платный вариант |
| Claude Sonnet 4 | Anthropic | Премиум-вариант |
| ~~`ollama/llama3.2:3b`~~ | ~~Ollama~~ | ~~Удалён политикой~~ — локальные модели не используются |
| ~~MLX (Qwen2.5-0.5B-4bit)~~ | ~~Локально~~ | ~~Удалён политикой~~ — ядро FOL работает через API |

### Память (6 слоёв)

| Слой | Файл / Источник | → Obsidian |
|------|-----------------|------------|
| **1. Identity** | `~/.secondself/identity.md` | `Profile/identity.md` |
| **2. Preferences** | `~/.secondself/preferences.md` | `Profile/preferences.md` |
| **2.5. Relationships** | `analyze/relationship_mapper.py` | `Profile/relationships.md` |
| **3. Context** | `context_engine/` (app + URL) | — (инжектится в промпт) |
| **4. Episodic** | `utils/episodic_writer.py` → `episodic.md` | `Episodic/events.md` |
| **5. Obsidian Vault** | `obsidian/` (client, vault, linker, sync, daily) | Vault-структура (11 папок) |
| **6. Procedural** | [PLAN] навыки | — |

### Основные команды

```bash
# === Запуск ===
./run_all.sh                     # все сервисы
./run_all.sh orchestrator        # только :8420
./run_all.sh agent               # только :8421
./run_all.sh fol                 # только :8754
./run_all.sh swift               # только SwiftUI приложение

# === Тесты ===
python3 -m pytest tests/ -v                  # корневые тесты
python3 -m pytest fol/tests/ -v              # тесты ядра FOL
python3 -m pytest tests/test_router.py -v    # роутер
python3 -m pytest tests/test_normalize.py -v # нормализация

# === Сборка ===
cd fol-app && swift build                 # SwiftUI
./build-app.sh                               # .app
./build-pkg.sh                               # .pkg

# === Проверки ===
./setup/smoke-test.sh                        # все сервисы
python3 scripts/e2e_check.py                 # health + MJPEG + SSE
./scripts/verify_scenarios.sh                # 5 сценариев end-to-end
./scripts/demo.sh                            # видео-демо
```

### Переменные окружения (.env)

| Переменная | Описание |
|------------|----------|
| `LLM_MODEL` | Основная модель (например `openrouter/nvidia/nemotron-3-super-120b-a12b:free`) |
| `OPENROUTER_API_KEY` | Ключ OpenRouter |
| `OPENAI_API_KEY` | Ключ OpenAI |
| `ANTHROPIC_API_KEY` | Ключ Anthropic (Claude) |
| `GEMINI_API_KEY` | Ключ Gemini |
| `LLM_FALLBACK_MODELS` | Цепочка запасных моделей через запятую |
| `LLM_MAX_TOKENS` | Лимит токенов ответа (по умолчанию 1500) |
| `LLM_TEMPERATURE` | Температура (по умолчанию 0) |
| `LLM_TIMEOUT` | Таймаут вызова (сек) |
| `TAVILY_API_KEY` | Веб-поиск Tavily |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth (Gmail/Calendar) |
| `GOOGLE_REDIRECT_URI` | Redirect URI (по умолчанию http://localhost:8080) |
| `FIREBASE_API_KEY` / `AUTH_DOMAIN` / `PROJECT_ID` | Firebase (web-слой) |
| `OBSIDIAN_API_KEY` | Obsidian Local REST API |
| `BRIDGE_PORT` | Порт bridge (по умолчанию 8422) |
| `AGENT_SERVER_URL` | URL agent-server (транспорт) |
| `ALLOWED_ORIGINS` | CORS для web |
| `USER_EMAIL` / `USER_NAME` | Идентичность пользователя |
| `FOL_LLM_BACKEND` / `FOL_LLM_MODEL` | Бэкенд ядра FOL (mlx/openai/anthropic/gemini) |
| `OPENROUTER_MODEL` | Модель OpenRouter для ядра FOL |

---

*Справочник составлен по состоянию кодовой базы. Последнее обновление: август 2026.*
