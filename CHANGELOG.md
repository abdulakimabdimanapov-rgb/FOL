# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] — 2026-08-20

### Added

**API Key Pool — автоматическая ротация ключей**
- `fol/modules/llm/key_pool.py` — пул до 99 ключей с автоматическим переключением при rate limit (429)
- Cooldown 5 минут (настраивается через `OPENROUTER_KEY_COOLDOWN`), после cooldown ключ возвращается в пул
- Thread-safe, работает в sync и async контекстах
- Интегрирован во все модули LLM: `analyze/_llm.py`, `analyze/_llm_async.py`, `fol/modules/llm/router.py`
- Ключи: `OPENROUTER_API_KEY`, `_KEY_2`, `_KEY_3`, ...`_KEY_99`

**Freebuff Auto-Start Bridge**
- `fol/modules/brain/freebuff_autostart.py` — Freebuff CLI запускается в фоне когда FOL стартует
- Используется как основной brain с fallback на текущий LLM
- Автоперезапуск при падении (до 2 попыток)
- Плавный fallback вместо краша при недоступности

### Changed

- `fol/modules/llm/brain.py` — `get_brain()` теперь поддерживает `freebuff_auto` + BrainRouter fallback
- `.env.example` / `.env.template` — добавлены настройки key pool и Freebuff auto-start
- README переписан на простом английском (A2-B1 уровень)

### Removed

- Старые .pkg файлы v1.2.0 удалены из `build/` и `Release/`

## [1.2.0] — 2026-08-18

### Added

**Brain-бэкенды — расширение мозга FOL**
- **CodebuffSDKBrainAdapter** (`fol/modules/llm/codebuff_adapter.py`): мозг через Codebuff SDK (`npx codebuff run --json`), поддержка streaming JSON-lines, реализует контракт `BrainInterface` (chat / chat_stream / acomplete). Активация: `FOL_BRAIN=codebuff` + `CODEBUFF_API_KEY`
- **FreebuffBrainAdapter** (`fol/modules/llm/freebuff.py`): placeholder для будущего HTTP API Freebuff. Документированы `FREEBUFF_REQUIREMENTS` (API URL, token, model). Активация: `FOL_BRAIN=freebuff`
- **BrainRouter** (`fol/modules/llm/brain_router.py`): роутинг brain-бэкендов с автоматическим fallback и мониторингом здоровья
- **Freebuff модели через OpenRouter**: DeepSeek V4 Flash (primary), MiMo 2.5 (fallback), Nemotron (fallback) — бесплатно, через LiteLLM

**Безопасность — критичные исправления**
- **Race condition в ConfirmationGate** (`fol/modules/tools/gate.py`): `asyncio.Lock()` на `_pending` и `_approved` словари, асинхронные `check()` / `approve()` / `revoke_expired()` — защита от конкурентных запросов в async-окружении
- **Shell injection** (`fol/core/app.py`): `_DANGEROUS_CMD_PATTERNS` (frozenset, 30+ паттернов) блокирует `rm -rf /`, `fork bomb`, `curl|sh`, `eval`, `python -c 'import os'`, `shutdown`, `mkfs`, `chmod 777 /`, `launchctl remove` и т.д. Regex-проверка pipe-to-shell. Defense-in-depth (поверх ConfirmationGate Level 5)
- **Memory leak** (`fol/core/app.py`): `_max_history = 100` — лимит хранимых диалогов в `_record_turn()`, защита от бесконечного роста памяти при долгих сессиях

**Тесты**
- 73 brain-теста (brain + brain_router + freebuff_adapter)
- 39 security-тестов (shell injection patterns)
- Итого FOL: 1073 passed

### Changed

- **`.env.example`**: добавлены Freebuff модели (DeepSeek V4 Flash, MiMo 2.5) + Codebuff SDK настройки
- **`.env.template`**: `LLM_MODEL=openrouter/deepseek/deepseek-v4-flash` (primary), fallback-цепочка обновлена
- **`fol/.env.example`**: Codebuff + Freebuff секции
- **`CLAUDE.md`**: секции 1.9 (Brain-бэкенды) + 1.10 (Security-фиксы)

### Fixed

- **Syntax error в `_DANGEROUS_CMD_PATTERNS`**: незакрытые строковые литералы (`"python -c 'import os'` → `"python -c 'import os'"`)
- **Test assertion в `test_brain.py`**: обновлено сообщение об ошибке для `FreebuffBrainAdapter`
- **Test assertion в `test_freebuff_adapter.py`**: обновлено описание ошибки для `freebuff`

## [1.1.0] — 2026-08-17

### Added

**Безопасность и гейтинг**
- **5-уровневый RiskScorer** (`fol/modules/tools/gate.py`): детерминированная оценка риска каждого инструмента на runtime — модель не может её обойти. SAFE_READ / UI_NAVIGATION → выполняется молча; INTERACTIVE_GUI → лёгкое auto-dismiss уведомление (PEEK_CONFIRM); FILE_MUTATION → блокировка до подтверждения (CONFIRM); SYSTEM_DANGEROUS → модалка с точной сигнатурой и таймаутом (STRICT_CONFIRM). Неизвестные инструменты → REJECT (fail-closed)
- **A2UI-подтверждения Level 3–5** (`fol-app/Views/`): `ActionInfoCard`, `PeekNotificationBadge`, `RiskConfirmCard`, `StrictModalCard` + интеграция в `A2UIRenderer` (allow/deny через `onAction`) — интерфейс риск-гейта в приложении

**Архитектура**
- **BrainInterface** (`fol/modules/llm/brain.py`): единый провайдер-независимый контракт рассуждений (chat / chat_stream / acomplete / classify / plan / select_tools / summarize / verify). Рабочий бэкенд — `FOL_BRAIN=current` (LiteLLMRouter: OpenRouter/Ollama/MLX, без изменений рантайма); `freebuff` честно отклоняется с ошибкой — у Freebuff нет программного интерфейса, без молчаливого фолбэка. Оркестратор (llm_bridge, memory_bridge, suggestion_engine) делегирует через `get_brain("current")`
- **Единый контекстный движок**: `fol/modules/input/context.py` (ContextEngine / ContextSnapshot) — активное приложение, URL браузера, скриншот + Vision OCR. Быстрый путь без экрана остаётся лёгким; каждый компонент best-effort и никогда не роняет вызывающего

**Голос**
- **Локальный STT без облачных ключей**: `fol/modules/input/voice/` с провайдером mlx-whisper (Apple Silicon, офлайн) + `POST /api/stt`; Swift-приложение само запускает FOL-бэкенд (:8754) и использует его для транскрипции. Микрофон работает в чисто локальных конфигурациях; при отсутствии mlx-whisper — точная ошибка установки вместо «ничего не услышано»

**Память**
- **Консолидация памяти** (`fol/modules/memory/consolidation.py` + `scheduler.py`): фоновый LLM-синтез дневных Work-Log → `Lessons.md` (дедупликация, метки времени) + `Daily-Consolidated/YYYY-MM-DD.md`

**Obsidian Brain v5** (`obsidian/`)
- Клиент переписан под контракт Local REST API 5.0.2: `write_note` шлёт JSON `{"content", "type": "file"}`, `search` — `POST /search/simple/?query=` с парсингом bare-array, PATCH с фолбэком «read → modify → write» для неиндексированных файлов. Новое: `list_notes`, `get_tags`, `move_note`, `append_to_note`, `execute_command`
- Vault bootstrap (`obsidian/vault.py`): `init_vault()` создаёт структуру (папки + `_index.md` + шаблоны + `Profile.md`), `refresh_indices()`, `bootstrap()`; шаблоны project / idea / decision / knowledge / daily в `Templates/`

**Контекст разговора (Этап 1 ROADMAP)**
- FOL понимает продолжения разговора: `ContextManager.is_follow_up()` (RU+EN), `get_current_topic()` извлекает сущности, блок привязки подключается в Orchestrator и живой путь FOL — модель резолвит местоимения даже на локальных моделях
- Фикс утечки XML tool-call: `personality.py` вырезает `<invoke>/<tool>/<param>` (модели эмитят их как текст)

**Режимы работы (Этап 2 ROADMAP)** (`fol/core/app.py`)
- Переключение голосом/текстом: **Companion** (по умолчанию), **Assistant**, **Agent**, **Focus**. Режим передаётся в контекст LLM, виден в `status`/`_help`; wake-word («FOL, …»), вежливая форма, падежи, EN/RU

**Shell-команды**
- `_extract_shell_command` (`fol/core/app.py`): матчит самый длинный префикс первым — «выполни команду pwd» даёт `pwd`, а не «команду pwd»; снимает хвостовой мусор («в терминале пожалуйста»), предложенную пунктуацию («pwd.» → `pwd`, но «ls .» сохраняется)

**Тесты**
- 39 (`fol/tests/core/test_shell_command_extract.py`) + 12 (`tests/test_obsidian_vault.py`) + 46 (context conversation, XML-strip) + 36 (`fol/tests/core/test_modes.py`)
- Новые наборы: риск-гейт, brain-абстракция, контекст-движок, voice (engine + mlx-whisper), консолидация памяти, качество ответов, chaos-тест agent-server, интеграции ToolRegistry / LLM-bridge / web-tier / safety-audit / final-response

### Changed

- **`context_engine/` — compatibility shim**: `snapshot.py`/`__init__.py` делегируют в FOL-движок (lazy import — импорт пакета не тянет `fol/` на sys.path); `ContextSnapshot` доступен через PEP 562 re-export
- **Голосовой ввод в приложении**: кнопка микрофона больше не требует облачный STT-ключ — проверяет доступность локального бэкенда (health-probe с ретраями)
- **`fol-app/Utilities/DesignTokens.swift`**: `backendPort 8000` → `folPort 8754` (FOL REST API) + health/STT эндпоинты
- **`.env.example`**: добавлен `FOL_BRAIN=current` (единственный доступный бэкенд)
- **Документация**: `docs/ARCHITECTURE.md` (5-уровневый риск-гейт + Brain-слой), `docs/INTERNAL_MIGRATION_MAP.md`, `ROADMAP_5_FEATURES.md` (Self-analysis → Multi-Agent → Voice → Plugins → Mobile)
- FOL тест-сьют вырос до **521 passed** (+4 новые тестовые папки после него)

### Fixed

- **P0: репозиторий не запускался** — две половины проекта (`Fol/` и `fol-app/`) были разнесены, код и документация ожидали единый корень. Слито в один корень: `fol/`, `orchestrator/`, `fol-app/`, `tests/` — импорты и все сервисы работают
- **`fol_command` handler binding** (`orchestrator/server.py`): контекст хэндлеров захватывал `call_fol_api` по ссылке при импорте — `patch()` и живой вызов не совпадали; теперь резолвится через модульный глобал в момент вызова
- **«Empty command» для fol_command**: валидация схемы отклоняла пустую `command` раньше хэндлера — теперь возвращается `{"error": "Empty command"}`
- **E2E false positive** (`scripts/e2e_check.py`): `litellm.APIError` (штатная деградация фолбэк-цепочки) больше не помечается как «ERROR»
- **Swift build после переезда**: битый кэш `SwiftShims` со старого пути — чистый пересбор работает
- **`build-app.sh` подпись**: `xattr -cr` перед codesign — сборка `.app` проходит без ручных шагов
- **Секреты**: `.env*` теперь в `.gitignore` (`.env.bak`/`.env.template` содержали реальные ключи); безопасные шаблоны с пустыми ключами коммитятся; репозиторий просканирован — чисто
- **«выполни команду pwd» падал**: regex-альтернатива `выполни` стояла раньше `выполни команду` — в шелл уходило `команду pwd`
- **Obsidian-память реально пишет и ищет**: v5-плагин отклонял сырой текст в PUT и не принимал GET-параметр search — «мозг» (заметки, daily, linker) молча не работал
- **PATCH на свежесозданных файлах**: metadata-cache Obsidian пуст сразу после PUT — надёжный клиентский фолбэк вместо 404
- Мёртвый ассерт в тесте (`or True`) заменён на проверку URL

## [1.0.0] — 2026-08-09

### Added

- **Response Formatter** (`orchestrator/response_formatter.py`): санитизация вывода агента — инструменты, JSON и имена tool-ов больше никогда не попадают в чат; пользователь видит только естественный текст. Новый SSE-тип `activity` с грубым безопасным статусом (`category` + `label`)
- **Personality-слой** (`fol/modules/llm/personality.py`): естественные контекстные ответы вместо «Done.»/«Готово.» (JARVIS-стиль, лёгкий юмор, язык пользователя) — внедрён в финальный слой FOL и все system prompt
- **Фильтрация JSON-tool-call в стриминге** (`analyze/_llm_async.py`): удержание токенов, которые могут быть JSON-вызовом инструмента (Ollama / слабые модели эмитят их как текст) — пользователь не видит сырой JSON
- **Проверка пустых ответов в фолбэк-цепочке**: пустой/`None` ответ модели теперь считается сбоем и переключает на следующую модель в `LLM_FALLBACK_MODELS` (sync + async + stream)
- **Запуск без перезапуска сервисов** (`fol-app/FOLApp.swift`): AppDelegate больше не убивает живые сервисы — проверяет порты 8420/8421/8754 и запускает только недостающие; чистка временных логов при выходе
- **Подпись .app при сборке** (`build-app.sh`): Developer ID при наличии, иначе ad-hoc codesign + проверка подписи
- **OpenRouter поддержка в FOL** (`fol/config/settings.py`): `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` (бесплатный Nemotron)

### Changed

- **Версия 1.0.0** — первый стабильный релиз (v1.0-beta стабилизирована)
- **VNC-фид и tool-call пилюли**: UI показывает только санитизированный статус (`activity`), без имён инструментов и аргументов (macOS + web + bridge)
- **Bridge**: ошибки передаются через `humanize_error()`, tool-calls никогда не шлются на телефон
- Тест-сьют вырос до **989 passed** (корневые) + **438 passed** (FOL)
- `py-applescript==1.0.3` (зафиксирована версия — стабильный API)

### Fixed

- **Утечка ключа в `.env.template`**: убран реальный Obsidian API-ключ из шаблона
- **`scripts/e2e_check.py`**: жёстко зашитый абсолютный путь заменён на автоопределение корня проекта — скрипт работает на любом Mac
- **Старые сборки**: удалены неактуальные `Second-Self-0.4.0.pkg` / `Second-Self-1.0.0.pkg` из `build/` (внутренняя версия 0.4.0)

## [1.0.0-beta] — 2026-08-06

### Added

- **Desktop tools в agent-server**: `close_app`, `drag`, `clipboard_get`, `clipboard_set`, `notify` — полный набор macOS-инструментов (AppleScript + PyAutoGUI + pbcopy/pbpaste)
- **Оркестратор**: новые инструменты зарегистрированы в `DESKTOP_TOOLS`, `TOOL_ENDPOINT_MAP` и system prompt — LLM может закрывать приложения, перетаскивать элементы, читать/писать буфер обмена и показывать уведомления
- **Web-чат (Next.js)**: реальный SSE-стриминг через `POST /api/chat/stream` → orchestrator:8420, потоковая отрисовка токенов, tool-call пилюли, состояния thinking/working/complete (устранён TODO)
- **Инфраструктура**: `Dockerfile` + `docker-compose.yml` для backend API (порт 8000)
- **CI**: `.github/workflows/test.yml` — pytest + Python-syntax check + Swift build на каждый push/PR
- **Interrupt speaking**: отправка сообщения или начало голосовой записи мгновенно прерывают речь JARVIS (TTS)
- **Тесты**: `tests/test_agent_server.py` — 14 тестов на новые desktop-инструменты (close_app, drag, clipboard, notify)
- **Фолбэк моделей (автопереключение)**: новый env `LLM_FALLBACK_MODELS` — цепочка запасных моделей через запятую. Если `LLM_MODEL` недоступна (лимит, аутэдж, ошибка), ассистент пробует каждую по очереди: `analyze/_llm.py` (sync), `analyze/_llm_async.py` (acompletion / astream / sync-completion). Модели без API-ключа пропускаются автоматически; цепочка логируется на старте (`Model chain: ...`)
- **`ROADMAP.md`**: идеи v2.0 (Plugin SDK, Knowledge Graph, Mobile Companion, Cloud Sync, Workflow Builder) + стратегия монетизации — отдельно от кодовой базы
- **Тесты**: `tests/test_llm_async.py` (новый файл) + фолбэк-тесты в `tests/test_llm.py` — цепочка моделей, пропуск без ключа, fallback при отказе primary

### Fixed

- Коллизия имён `server.py` в тестах: agent-server загружается через `importlib` с уникальным именем модуля
- **Obsidian-ключ не загружался при старте**: `obsidian/config.py` читал `os.environ` до вызова `load_dotenv()` — живая память была молча отключена. Теперь `.env` загружается перед чтением конфига
- **`save_to_obsidian` падал с `TypeError: can only concatenate str (not "list")`**: LLM передаёт `tags` строкой или вложенным списком вместо `list[str]`. Добавлена нормализация в `obsidian/vault.py` (стратегическая точка для всех сохранений) + защитная нормализация `folder/title/content/tags` в `obsidian/tools.py`
- **Зацикливание агента**: маленькие модели вызывали один и тот же инструмент бесконечно. Добавлен Loop Guard (`MAX_REPEATED_TOOL_CALLS`, `_tool_call_signature`) в оба агентных цикла — прерывает после N повторных вызовов подряд, закрывает историю валидными `tool_result`
- **`max_tokens=8192` жёстко зашит в стриминг**: игнорировал `LLM_MAX_TOKENS` из `.env` и мог превышать лимиты провайдера — теперь значение берётся из конфига
- **Тест `test_command_returns_actions`**: запрос выполнялся вне `with stack:` блока моков — исправлен
- **`openrouter/...` в `_llm_async.py`**: проверка префикса теперь идёт ДО substring-матча `"anthropic"` — `openrouter/anthropic/claude` больше не ошибочно требует `ANTHROPIC_API_KEY`

### Changed

- **Двухэтапный выбор инструментов (двухэтапная категоризация)**: вместо 50 инструментов модель получает 5–12, релевантных категории задачи (email/calendar/docs/memory/web/coding/desktop). Радикально улучшает точность tool calling даже у слабых моделей (llama3.2:3b выбирает инструменты правильно с узким набором)
- **Правила остановки в system prompt**: модель теперь останавливается после получения ответа (1–5 вызовов), а не копает до `max_steps`
- **LLM_MODEL**: переключён на бесплатную `openrouter/nvidia/nemotron-3-super-120b-a12b:free` (120B MoE, отличный tool calling, не тратит кредиты). Рабочие ключи OpenRouter/OpenAI сохранены в `.env`
- Тест-сьют вырос до **872 passed** (+21 тест: категоризация, loop guard, obsidian-нормализация)
- **`scripts/verify_scenarios.sh`**: скрипт верификации 5 сценариев ежедневного использования
- **Первый официальный релиз v1.0-beta** — рабочее ядро с подтверждённой архитектурой (876+ тестов, 5 сценариев end-to-end); фокус смещается на выпуск, документацию и обратную связь

## [0.4.0] — 2026-07-30

### Changed

- Версия проекта обновлена с `0.3.0` → `0.4.0`
- Пересобран `.app` и `.pkg` установщик

### Removed

- Удалены старые сборки из `build/` — только последняя версия

## [0.3.0] — 2026-07-30

### Added

- **Статус-логи в AppDelegate**: события `Chat opened`, `Input field focused`, `Message sent` логируются через `NotificationCenter` и отображаются в меню-баре
- **Настроена локальная Ollama**: `LLM_MODEL=ollama/llama3.2:3b` — AI работает полностью локально, без API ключей
- **Веб-поиск через Tavily**: установлен `TAVILY_API_KEY` — Twin может искать информацию в интернете
- **CHANGELOG.md**: начата история версий проекта

### Fixed

- **ChatInputBar — фокус поля ввода**: убран `.id(textFieldID)`, который ломал `@FocusState` на macOS 14 — теперь поле ввода стабильно принимает клавиатурный ввод (#1)
- **NotchPanel — keyWindow**: добавлен `override var canBecomeKey: Bool { true }` — гарантирует что панель становится key window для клавиатуры
- **Reclaim keyWindow при Cmd+Tab**: при клике на панель на stage 2 после переключения приложений фокус восстанавливается
- **Actor-isolation warning**: исправлен в `observeUIEvents()` через `Task { @MainActor in }`

### Changed

- Версия проекта обновлена с `0.2.0` → `0.3.0`
- Собран `.app` (2.6M) и `.pkg` (4.0M) установщик
- Старые сборки удалены из `build/` — только последняя версия

## [0.2.0] — 2026-07-29

### Added

- Объединение FOL и SecondSelf в единый проект
- Notch UI (SwiftUI, NSPanel)
- Билингвальный routing (русский + английский)
- 500+ Python тестов

---

[1.3.0]: https://github.com/abdulakimabdimanapov-rgb/SecondSelf/releases/tag/v1.3.0
[1.2.0]: https://github.com/abdulakimabdimanapov-rgb/SecondSelf/releases/tag/v1.2.0
[1.0.0-beta]: https://github.com/abdulakimabdimanapov-rgb/SecondSelf/releases/tag/v1.0-beta
[0.4.0]: https://github.com/abdulakimabdimanapov-rgb/SecondSelf/releases/tag/v0.4.0
[0.3.0]: https://github.com/abdulakimabdimanapov-rgb/SecondSelf/releases/tag/v0.3.0
[0.2.0]: https://github.com/abdulakimabdimanapov-rgb/SecondSelf/releases/tag/v0.2.0
