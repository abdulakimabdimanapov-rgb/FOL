# FOL_FREEBUFF_AUDIT — Freebuff как Brain Provider для FOL

> Дата аудита: 2026-08-17 · Версия проекта: 1.1.0
> Статус: **исследование завершено, код НЕ изменялся** (по требованию — сначала аудит)
> Цель: FOL = единый продукт (Freebuff = Brain, FOL Core = Nervous System,
> Second Self = Body/UI, Obsidian = Long-Term Memory, Tools = Hands,
> Voice = Ears+Mouth, Vision = Eyes) при полной сохранности существующих функций.

---

## 1. Текущая архитектура Brain

### 1.1 Контракт — `BrainInterface` (`fol/modules/llm/brain.py`)

Единая, провайдер-независимая абстракция рассуждений. Малый контракт: только
reasoning, никогда память, никогда инструменты.

| Метод | Назначение | Контракт возврата |
|---|---|---|
| `chat(messages, system, tools, max_tokens, temperature)` | завершение диалога | `str`; `BrainError` при полном отказе |
| `chat_stream(...)` | стриминг | async-итератор событий `{"type": "token"\|"tool_use"\|"done"\|"error", ...}` |
| `acomplete(...)` | async-завершение | `{"content", "tool_calls", "stop_reason"}` |
| `classify(text)` | интент (метки из `BRAIN_INTENT_LABELS`) | `str` |
| `plan(task, context)` | план шагов | `list[str]` |
| `select_tools(task, tools)` | выбор имён инструментов из предоставленного списка | `list[str]` (никогда не выдумывает) |
| `summarize(text, max_words)` | краткое изложение | `str` |
| `verify(claim, evidence)` | вердикт: supported / partially supported / unsupported / insufficient evidence | `str` |

Интроспекция (не абстрактная, переопределяется бэкендами): `available`,
`status()`, `model_chain()`, `available_providers()`, `test_connection()`.

Ошибки: `BrainError` → `BrainConfigurationError` (невалидный/недоступный выбор
бэкенда) и `BrainUnavailableError` (бэкенд выбран, но не вызываем).

### 1.2 Бэкенды

```
BrainInterface (fol/modules/llm/brain.py)
   ├── CurrentLLMAdapter      ← РАБОЧИЙ (по умолчанию)
   │     └── LLMRouter (fol/modules/llm/router.py — LiteLLM: OpenRouter/Ollama/MLX/OpenAI)
   │           └── фолбэк-цепочка LLM_FALLBACK_MODELS, fallback_log()
   └── FreebuffBrainAdapter   ← ЧЕСТНЫЙ плейсхолдер (available=False,
         каждый метод → BrainUnavailableError, стриминг → error-событие)
```

- `CurrentLLMAdapter` — тонкий делегат над каноническим `LLMRouter`. Ноль
  собственной логики роутинга/фолбэка — всё в `modules.llm.router`/бэкендах.
- `FreebuffBrainAdapter` уже существует и **не притворяется вызываемым**:
  `available=False`, `status()={"reason": "No supported programmatic interface (audited)."}`,
  все reasoning-методы бросают `BrainUnavailableError`. Никогда не трогает
  недокументированные токены/внутренности CLI.

### 1.3 Фабрика — `get_brain(name=None, *, router=None)`

Порядок разрешения: явный `name` → env `FOL_BRAIN` → `"current"`.

| Значение | Поведение |
|---|---|
| `current` / `local` / `litellm` / `llm` | → `CurrentLLMAdapter` (как сейчас, без изменений) |
| `freebuff` | → `BrainConfigurationError` («не программный рантайм-бэкенд, поставьте FOL_BRAIN=current») — **без молчаливого фолбэка** |
| всё остальное | → `BrainConfigurationError` («Unknown FOL_BRAIN») |

### 1.4 Потребители (кто сидит на BrainInterface)

| Потребитель | Путь вызова |
|---|---|
| `orchestrator/llm_bridge.py` | legacy-контракт `llm_astream`/`llm_acompletion`/`llm_completion_sync` → `CurrentLLMAdapter(router=...)`; при недоступности канонического роутера — прозрачный фолбэк на `analyze/_llm_async` (legacy) |
| `orchestrator/suggestion_engine.py` | `get_brain("current").chat(...)` |
| `fol/modules/llm/proactive.py` | `get_brain("current").chat(...)` |
| Транзитивно: `orchestrator/server.py`, `analyze/*`, `obsidian/*`, `src/synthesis/profile.py` | через bridge → BrainInterface |
| `fol/modules/llm/__init__.py` | re-export `BrainInterface`, `get_brain`, ... |

### 1.5 Существующие тесты Brain/LLM

- `fol/tests/modules/llm/test_brain.py` (346 строк): контракт интерфейса,
  `CurrentLLMAdapter` (делегация в роутер), `FreebuffBrainAdapter`
  (unavailable-ошибки на всех методах, error-событие в стриминге, пустые
  introspection), `get_brain` (default=current, env-выбор, `freebuff` → fail
  clearly, unknown → fail, **no silent fallback from freebuff**).
- `tests/test_llm_bridge.py`: bridge → BrainInterface (мок `get_brain`),
  контрактная совместимость, fallback на legacy при недоступности роутера.
- `fol/tests/modules/llm/test_proactive.py`, `test_personality.py` и др. —
  опосредованно через `get_brain("current")`.

---

## 2. Точки интеграции (что именно будет затронуто)

1. **`get_brain()`** (`fol/modules/llm/brain.py`) — единственная фабрика выбора
   бэкенда. Здесь включается роутинг `freebuff`.
2. **`BrainInterface`** — контракт НЕ меняется (требование пользователя).
   `FreebuffBrainAdapter` обязан реализовать все его методы.
3. **`fol/modules/llm/__init__.py`** — экспорт новых символов
   (`BrainRouter`, адаптер) для внешних потребителей.
4. **`orchestrator/llm_bridge.py`** — потребитель через
   `CurrentLLMAdapter(router=...)` напрямую. Если `FOL_BRAIN=freebuff` —
   bridge должен получать бэкенд через `get_brain()` (единая точка), а не
   конструировать `CurrentLLMAdapter` вручную (иначе выбор FOL_BRAIN не
   дойдёт до bridge). Требуется аккуратная правка: bridge берёт бэкенд из
   `get_brain()`, legacy-фолбэк сохраняется только при недоступности `fol/`.
5. **`fol/modules/llm/proactive.py`, `orchestrator/suggestion_engine.py`** —
   уже идут через `get_brain("current")`; смена `FOL_BRAIN` автоматически
   переключит их на Freebuff-бэкенд (правки не нужны, только проверка).
6. **Конфигурация**: `.env.example` (корень) и `fol/.env.example` — блок
   Brain, `FOL_BRAIN=current`; добавить документированные (но не активные)
   `FREEBUFF_*` ключи.
7. **Safety Layer** — НЕ трогается: `ToolRegistry` → `ConfirmationGate`
   (`fol/modules/tools/gate.py`, RiskScorer 5 уровней, fail-closed) остаётся
   полностью под контролем FOL. Freebuff получает только «голое» reasoning,
   никогда — прямое исполнение системных действий.
8. **Документация**: `docs/ARCHITECTURE.md` (§6.5), `docs/INTERNAL_MIGRATION_MAP.md`
   (строки 103, 108, 131), `docs/PROJECT_DESCRIPTION.md` (§4.2), `CHANGELOG.md`.

---

## 3. Как Freebuff реально можно подключить (ФАКТЫ, не догадки)

### 3.1 Что проверено (2026-08-17)

**A. Локально установленный CLI (`freebuff@0.0.124`, npm global):**

```
$ freebuff --help
Usage: freebuff [options] [command]
Arguments:
  command    Command to run (choices: "login")
Options:
  -v, --version
  --continue [conversation-id]
  --cwd <directory>
  -h, --help
```

Вывод: **интерактивный TUI**. Единственная подкоманда — `login`. Нет
неинтерактивных флагов (`--print`, `--json`, `exec`, `run`), нет server/socket
режима, нет стабильного машинного контракта вывода. → Как runtime-бэкенд CLI
**непригоден** (и требование №1 пользователя: не придумывать API).

**B. npm-метаданные:**
- `freebuff@0.0.149` (latest) — обёртка-лаунчер 63.7 kB, зависимость: `tar`.
  Пакет скачивает бинарник приложения. Никакого SDK/API в нём нет.
- `@codebuff/sdk@0.10.7` — официальный SDK, Apache-2.0, 64.8 MB, зависимости
  включают `@ai-sdk/anthropic`, `ai@^5`, `ws`. Это SDK **Codebuff**
  (codebuff.com — платный продукт с API-ключами), а НЕ бесплатного сервиса
  Freebuff. README Freebuff: «Freebuff is built on Codebuff ... that powers its
  orchestration, tools, and SDK» — SDK относится к фреймворку Codebuff,
  документированного пути к бесплатным моделям Freebuff через него нет.

**C. Сайт freebuff.com (README GitHub CodebuffAI/freebuff):**
Пять продуктов: Freebuff Desktop, Freebuff CLI, Freebuff Web, Freebuff Cloud,
Freebuff Chat. Модели: DeepSeek V4 Pro/Flash, GPT-5.6 Luna, MiniMax M3, MiMo 2.5,
GLM 5.2, Gemini 3.1 Flash Lite (специализированные задачи). **Нигде не
документирован публичный HTTP API / SDK бесплатного сервиса.** Авторизация —
аккаунт Freebuff + сессии с лимитами (limited mode: 6 сессий × 1 час/день);
рекламная модель. Прямой программный доступ к этим моделям не описан.

**D. Локальное окружение:** нет `~/.freebuff`, `~/.config/freebuff`,
серверных процессов/сокетов Freebuff, npm-глобальных модулей кроме самого CLI.

### 3.2 Вывод (честный, по требованию №5)

> **У бесплатного Freebuff сегодня НЕТ поддерживаемого программного интерфейса
> для использования как runtime-бэкенда FOL:**
> - CLI — интерактивный TUI (проверено на установленном бинарнике);
> - публичного HTTP API/сервера/сокета — нет;
> - SDK существует только у **Codebuff** (платный, API-ключи) и не
>   документирует доступ к бесплатным моделям Freebuff;
> - использовать SDK Codebuff = интегрировать ДРУГОЙ платный продукт и
>   протаскивать API-ключи в FOL Core — запрещено требованиями №4 и №7.

**Поэтому (требования №5–№7):**
1. `FOL_BRAIN=freebuff` → честная `BrainConfigurationError` (как сейчас),
   без симуляции, без фиктивных endpoints, без обхода авторизации/лимитов.
2. `FreebuffBrainAdapter` — реальный класс, реализующий `BrainInterface`,
   с понятной ошибкой и документацией того, что требуется для подключения.
3. Никаких API-ключей через FOL Core: когда интерфейс появится, креды читает
   сам адаптер из env (аналогично `OPENAI_API_KEY` в `router.py`).

### 3.3 Что требуется, чтобы подключение стало возможным (документируемые условия)

Любой ОДИН из официальных вариантов (решает Freebuff, не FOL):

| Вариант | Что нужно | Как подключится FOL |
|---|---|---|
| **A. Официальный HTTP API** | Endpoint `chat/completions`-стиля + токен-авторизация (как у Codebuff/Anthropic) | `FreebuffBrainAdapter` поверх httpx/aiohttp: `chat`, `chat_stream` (SSE), `acomplete`; env `FREEBUFF_API_URL`, `FREEBUFF_API_TOKEN` |
| **B. Headless-режим CLI** | `freebuff run/exec --json` (или `serve` с Unix-socket/локальным HTTP), стабильный контракт вывода | Адаптер через subprocess/локальный HTTP; парсинг документированного JSON |
| **C. Официальный Freebuff SDK** | Собственный SDK (не Codebuff) с chat/streaming | Адаптер-обёртка над SDK (Python-биндинг или subprocess/HTTP мост) |

Дополнительно: документированные лимиты (limited mode: 6 сессий/день) и
авторизация (login) должны быть учтены адаптером (таймауты, понятные ошибки
«session limit reached»). Это же требование №4: не обходить платные/лимитные
ограничения — адаптер обязан честно их пробрасывать пользователю.

---

## 4. Файлы, которые нужно изменить

| Файл | Изменение |
|---|---|
| `fol/modules/llm/brain.py` | Вынести `FreebuffBrainAdapter` в отдельный модуль (re-export для совместимости); встроить `BrainRouter` в `get_brain()`; сохранить честную ошибку для `freebuff`; НЕ менять `BrainInterface` и `CurrentLLMAdapter` |
| `fol/modules/llm/__init__.py` | Экспорт `BrainRouter` (и re-export адаптера) |
| `orchestrator/llm_bridge.py` | Брать бэкенд через `get_brain()` вместо ручного `CurrentLLMAdapter(router=...)`, чтобы `FOL_BRAIN` реально доходил до bridge; legacy-фолбэк сохранить только при недоступности `fol/` |
| `.env.example` (корень) + `fol/.env.example` | Документировать будущие ключи `FREEBUFF_API_URL` / `FREEBUFF_API_TOKEN` / `FREEBUFF_TIMEOUT` как «не активны до появления официального интерфейса» |
| `docs/ARCHITECTURE.md` (§6.5) | Схема Brain Router, статус Freebuff (audit 2026-08-17) |
| `docs/INTERNAL_MIGRATION_MAP.md` | Строки 103/108/131: обновить статус |
| `docs/PROJECT_DESCRIPTION.md` (§4.2) | Дополнить раздел Freebuff |
| `CHANGELOG.md` | Запись для следующей версии |

## 5. Новые файлы, которые нужно создать

| Файл | Назначение |
|---|---|
| `fol/modules/llm/brain_router.py` | **Brain Router** — композиция бэкендов в приоритетном порядке (freebuff → current) с учётом фолбэка. Публичный класс `BrainRouter(BrainInterface)` |
| `fol/modules/llm/freebuff.py` | `FreebuffBrainAdapter` (перенесён из brain.py) + валидация конфигурации (`_FREEBUFF_REQUIREMENTS`), понятные ошибки, документация условий подключения |
| `fol/tests/modules/llm/test_brain_router.py` | Тесты роутера: порядок, strict-режим, фолбэк, статус |
| `fol/tests/modules/llm/test_freebuff_adapter.py` | Тесты адаптера: init, конфигурация, unavailable, контракт |

## 6. Риски

| Риск | Митигация |
|---|---|
| **Сломать 2049+ тестов** (особенно `test_brain.py`: `freebuff` → `BrainConfigurationError`, «no silent fallback») | Роутер вводится аддитивно; поведение `FOL_BRAIN=current` и `FOL_BRAIN=freebuff` остаётся как сейчас (strict fail). Все существующие тесты проходят без правок |
| **Молчаливый фолбэк** freebuff→current против воли пользователя | Explicit-freebuff всегда fail clearly при недоступности (существующий инвариант, покрыт тестом `test_no_silent_fallback_from_freebuff`) |
| **Выдуманный API / фиктивные endpoints** | Запрещено (требование №3); адаптер не содержит ни одного URL — только проверку конфигурации и ошибку |
| **Обход авторизации/лимитов Freebuff** | Запрещено (требование №4); адаптер честно пробрасывает «session limit reached» |
| **Утечка API-ключей через FOL Core** | Креды читаются адаптером из env на месте вызова, не передаются через ядро (требование №7) |
| **Обход Safety Layer** | Freebuff получает только reasoning; исполнение инструментов — строго через `ToolRegistry → ConfirmationGate` (неизменяемо) |
| **Контракт стриминга** (`{"type": ...}` события) | Адаптер обязан маппить в тот же event-контракт; тест на error-событие уже есть |
| **Bridge берёт `CurrentLLMAdapter` вручную** | Правка: bridge через `get_brain()`; regression-тесты `tests/test_llm_bridge.py` |
| **Регистронезависимая ФС** (FOL/fol) | Не затрагивается — новые файлы внутри `fol/modules/llm/` |
| **CI / сборка** | `swift build` не зависит от Python-изменений; pytest в CI покрывает новые тесты |

## 7. План миграции

**Фаза 0 — Аудит (ЭТОТ ДОКУМЕНТ).** Исследование интерфейса Freebuff завершено,
вывод: программного интерфейса нет → честная ошибка, без симуляции.

**Фаза 1 — Слои без изменения поведения (аддитивно, всё зелёное):**
1. Извлечь `FreebuffBrainAdapter` из `brain.py` в `fol/modules/llm/freebuff.py`
   (re-export из brain.py; поведение не меняется).
2. Создать `fol/modules/llm/brain_router.py`: `BrainRouter` — контейнер
   приоритетного списка бэкендов; пока используется только как внутренний
   механизм `get_brain()` при `FOL_BRAIN=freebuff` → strict fail
   (как сегодня), т.е. роутер ничего не меняет для `current`.
3. `get_brain()`: `freebuff` → создаёт `BrainRouter([freebuff_adapter,
   current_adapter])`, но адаптер `available=False` → `BrainConfigurationError`
   с сообщением, которое перечисляет требования (раздел 3.3) — вместо
   короткой строки. Ошибка остаётся `BrainConfigurationError`.
4. Bridge через `get_brain()` (единая точка выбора).
5. `FREEBUFF_*` ключи в `.env.example` (задокументированы, не активны).
6. Тесты: `test_freebuff_adapter.py`, `test_brain_router.py` (роутер в
   strict-режиме, ошибки, статус, контракт).

**Фаза 2 — Когда Freebuff опубликует официальный интерфейс (внешняя зависимость):**
7. Реализовать транспорт в `freebuff.py` под выбранный вариант (A/B/C из 3.3).
8. `FOL_BRAIN=freebuff` → роутер `[freebuff, current]` с фолбэком на runtime-
   ошибки (таймауты/лимиты), строгий fail только при недоступности конфигурации.
9. Конфиг: `FREEBUFF_API_URL`/`FREEBUFF_API_TOKEN`/`FREEBUFF_TIMEOUT`.
10. Включить и проверить end-to-end (см. план тестирования).

**Фаза 3 — «Единый продукт»:** Freebuff = Brain (через роутер), FOL Core =
nervous system, UI = FOL.app, память = Obsidian, руки = Tools, голос/глаза =
voice/vision — всё через существующие слои, ничего не ломая.

## 8. План тестирования

**Существующие (должны остаться зелёными без правок):**
- `fol/tests/modules/llm/test_brain.py` — контракт, current, freebuff-strict, no-silent-fallback
- `tests/test_llm_bridge.py` — bridge контракт + legacy-фолбэк
- Полные сьюты: `pytest tests/` + `pytest fol/tests/` (2049+), `cd fol-app && swift build`

**Новые (Фаза 1):**

| Группа | Кейсы |
|---|---|
| **Initialization** (`test_freebuff_adapter.py`) | адаптер создаётся; `available=False`; `status()` без секретов; `name=="freebuff"` |
| **Configuration** | нет `FREEBUFF_*` → понятная ошибка; конфиг валидируется только при наличии официального интерфейса (сейчас — unavailable) |
| **Routing** (`test_brain_router.py`) | порядок бэкендов; strict: freebuff недоступен → `BrainConfigurationError` (не молчаливый current); `FOL_BRAIN=current` → ровно как сейчас; unknown → error |
| **Chat / Streaming** | `chat` → `BrainUnavailableError`; `chat_stream` → единственное `{"type": "error"}` событие; `acomplete` → raise |
| **Errors / Timeout** | все ошибки — подтипы `BrainError`; сообщение перечисляет требования подключения |
| **Unavailable Freebuff** | каждый метод контракта (classify/plan/select_tools/summarize/verify) → `BrainUnavailableError` |
| **Fallback** | роутер с [freebuff, current]: при `available=False` у freebuff — strict fail (инвариант); когда появится транспорт — fallback на current на runtime-ошибках (Фаза 2) |
| **Safety integration** | тест: brain-ответ не может инициировать исполнение инструмента в обход `ConfirmationGate` (gate замочен, вызов из brain отсутствует); `fol/tests/modules/tools/test_gate.py` не меняется |
| **BrainInterface compatibility** | адаптер реализует ВСЕ абстрактные методы (мета-тест, как в `test_brain.py`) |

**E2E после Фазы 1:** `FOL_BRAIN=current` → `./scripts/e2e_check.py` (14/14),
`verify_scenarios.sh`, health всех портов 8420/8421/8754 — без изменений.

---

## Резюме

- Контракт `BrainInterface` менять не нужно — Freebuff реализует его как есть.
- **Freebuff сегодня не имеет программного интерфейса** (проверено: CLI = TUI,
  публичного API/SDK бесплатного сервиса нет; SDK — у Codebuff, платного).
- Поэтому Фаза 1: честный `FreebuffBrainAdapter` + `BrainRouter` + конфиг +
  тесты, поведение `current` не меняется, `freebuff` fail clearly.
- Фаза 2 запустится только когда Freebuff опубликует официальный интерфейс
  (варианты A/B/C в разделе 3.3).
- Safety Layer (RiskScorer, ConfirmationGate, fail-closed) остаётся под полным
  контролем FOL во всех фазах.
