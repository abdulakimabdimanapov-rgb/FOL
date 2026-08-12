# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Shell-command extraction fix** (`fol/core/app.py`): `_extract_shell_command`
  матчит САМЫЙ длинный префикс первым — «выполни команду pwd» теперь даёт
  `pwd`, а не `команду pwd` (было: `/bin/sh: команду: command not found`).
  Снимает хвостовой мусор повторно («в терминале пожалуйста», «in the
  terminal please»), предложенную пунктуацию («pwd.» → `pwd`, но «ls .»
  сохраняется), а «запусти команду X» роутится через app_match как команда.
- **39 тестов** (`fol/tests/core/test_shell_command_extract.py`): RU/EN
  префиксы, пунктуация, составной мусор, фолбэк «запусти команду».

### Fixed

- **«выполни команду pwd» падал** — regex-альтернатива `выполни` стояла
  раньше `выполни команду`, поэтому в шелл уходило `команду pwd`.

### Added

- **Obsidian Brain v5** (`obsidian/`): клиент переписан под контракт Local
  REST API 5.0.2 — `write_note` шлёт JSON `{"content", "type": "file"}`,
  `search` — `POST /search/simple/?query=` с парсингом bare-array ответа,
  PATCH с фолбэком «read → modify → write» для файлов, которые Obsidian ещё
  не проиндексировал. Новые возможности: `list_notes` (API + диск), `get_tags`,
  `move_note`, `append_to_note`, `execute_command`.
- **Vault bootstrap** (`obsidian/vault.py`): `init_vault()` создаёт всю
  структуру (папки + `_index.md` + шаблоны + `Profile.md`),
  `refresh_indices()` перегенерирует индексы из реальных заметок,
  `bootstrap()` — one-shot инициализация с синхронизацией `~/.secondself`.
- **Шаблоны заметок** (`obsidian/config.py`): project / idea / decision /
  knowledge / daily в `Templates/`.
- 12 новых тестов (`tests/test_obsidian_vault.py`) на v5-контракт: JSON body
  записи, search query-параметр, фолбэк PATCH, вставка под заголовок.

### Fixed

- **Obsidian-память реально пишет и ищет**: v5 плагин отклонял сырой текст в
  PUT и не принимал GET-параметр search — весь «мозг» (заметки, daily,
  linker) молча не работал, хотя `check_connection()` мог вернуть True.
- **PATCH на свежесозданных файлах**: markdown-patch 2.0 резолвит target
  только через metadata-cache Obsidian; сразу после PUT файла там нет →
  надёжный клиентский фолбэк вместо 404.
- Мёртвый ассерт в тесте (`or True`) заменён на проверку URL.

### Added

- **Context Conversation (Этап 1 ROADMAP)**: FOL теперь понимает продолжения разговора — «Найди новости про OpenAI» → «А какая из них самая важная?» → FOL отвечает про OpenAI. `ContextManager.is_follow_up()` детектит follow-up сообщения (RU+EN), `get_current_topic()` извлекает актуальные сущности из истории (OpenAI, GPT и т.п.), а `get_follow_up_context()` собирает блок привязки для промпта. Блок подключается и в Orchestrator, и в живой путь `FOL._get_context()` (через зеркалирование истории в ContextManager) — модель явно видит текущую тему и прошлое сообщение и резолвит местоимения («них», «его», «it», «they») корректно даже на локальных моделях. Детекция защищена от ложных срабатываний: длинные «А вчера я ходил в кино…» считаются новой темой, а не follow-up
- **Фикс утечки XML tool-call**: `personality.py` теперь вырезает и XML-блоки `<invoke>/<tool>/<param>` (модели эмитят их как текст), а не только JSON — в чате не появляется сырой разметки (найдено живым тестом)
- **Тесты**: `fol/tests/core/test_context_conversation.py` + расширения `test_final_response.py` — 46 новых тестов (детекция follow-up, извлечение темы, привязка в промпте, XML-strip)

### Added

- **Режимы работы (Этап 2 ROADMAP)** (`fol/core/app.py`): FOL переключается голосом или текстом — «FOL, режим фокус» / «режим ассистент» / «agent mode». Режимы: **Companion** (обычное общение, по умолчанию), **Assistant** (задачи на Mac напрямую), **Agent** (сложные многошаговые задачи), **Focus** (минимум разговоров, максимум действий — короткие ответы). Активный режим передаётся в контекст LLM (`CURRENT MODE: …`), виден в `status` и `_help`. Поддержаны wake-word («FOL, …»), вежливая форма («… пожалуйста»), падежи («режим фокуса») и обе языковые конструкции («mode focus» / «focus mode»)
- **Тесты**: `fol/tests/core/test_modes.py` — 36 тестов (переключение, статус, wake-word, вежливость, регистр, защита «режим голоса»)

### Changed

- FOL тест-сьют вырос до **521 passed**

## [1.0.0] — 2026-08-09

### Added

- **Response Formatter** (`orchestrator/response_formatter.py`): санитизация вывода агента — инструменты, JSON и имена tool-ов больше никогда не попадают в чат; пользователь видит только естественный текст. Новый SSE-тип `activity` с грубым безопасным статусом (`category` + `label`)
- **Personality-слой** (`fol/modules/llm/personality.py`): естественные контекстные ответы вместо «Done.»/«Готово.» (JARVIS-стиль, лёгкий юмор, язык пользователя) — внедрён в финальный слой FOL и все system prompt
- **Фильтрация JSON-tool-call в стриминге** (`analyze/_llm_async.py`): удержание токенов, которые могут быть JSON-вызовом инструмента (Ollama / слабые модели эмитят их как текст) — пользователь не видит сырой JSON
- **Проверка пустых ответов в фолбэк-цепочке**: пустой/`None` ответ модели теперь считается сбоем и переключает на следующую модель в `LLM_FALLBACK_MODELS` (sync + async + stream)
- **Запуск без перезапуска сервисов** (`SecondSelf/SecondSelfApp.swift`): AppDelegate больше не убивает живые сервисы — проверяет порты 8420/8421/8754 и запускает только недостающие; чистка временных логов при выходе
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

[1.0.0-beta]: https://github.com/abdulakimabdimanapov-rgb/SecondSelf/releases/tag/v1.0-beta
[0.4.0]: https://github.com/abdulakimabdimanapov-rgb/SecondSelf/releases/tag/v0.4.0
[0.3.0]: https://github.com/abdulakimabdimanapov-rgb/SecondSelf/releases/tag/v0.3.0
[0.2.0]: https://github.com/abdulakimabdimanapov-rgb/SecondSelf/releases/tag/v0.2.0
