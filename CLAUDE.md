# FOL — Документация проекта

> 📐 **Master architecture:** `FOL_UPGRADE.md` — полный план развития проекта.
> 🎯 **Design system:** `DESIGN.md` — цвета, шрифты, анимации.
> 🔧 **Quick start:** `cd fol-app && swift build && swift run`

---

## 1. ЧТО БЫЛО СДЕЛАНО (ИЗМЕНЕНИЯ)

### 1.1 VoiceInputButton — Анимация пульсации при записи

**Файл:** `fol-app/Views/VoiceInputButton.swift`

- Idle: оливковая иконка микрофона
- Recording: **две пульсирующие кольцевые обводки** + свечение (`glowRadius`)
- Transcribing: спиннер внутри кнопки
- Error: пружинная анимация тряски (`interpolatingSpring`)
- Плавные переходы: `.scale.combined(with: .opacity)`

### 1.2 AudioWaveformView — Физическая симуляция волн

**Файл:** `fol-app/Views/ChatInputBar.swift`

- Каждая полоска — масса-пружина-демпфер (`stiffness: 180`, `damping: 12`)
- Волна распространяется от центра к краям с затуханием
- Дыхание в тишине (естественная анимация при `audioLevel < 0.02`)
- Градиентная заливка сверху вниз
- Обновляется при 60fps через `Timer.publish`

### 1.3 Shimmer/Glow эффект на поле ввода

**Файл:** `fol-app/Views/ChatInputBar.swift`

- **Shimmer-полоса**: анимированный градиент слева направо (1.8s)
- **Пульсирующая рамка**: `Color.ssCream` пульсирует 0→35% (1.2s)
- **Тень-свечение**: радиус 14→24pt, пульсация (0.9s)
- `.onChange(of: voiceState)` + `.onAppear` для корректного старта/стопа

### 1.4 ChatView — Плавное появление сообщений

**Файл:** `fol-app/Views/ChatView.swift`

- `.asymmetric` transition: вставка с `offset(y: 8)` + scale + opacity
- Исчезновение: только scale + opacity

### 1.5 Bilingual Routing (русский + английский)

**Файлы:** `orchestrator/agents/router.py`, `orchestrator/server.py`

**router.py:**
- Русские ключевые слова для 5 агентов (Architect, Coder, Reviewer, Researcher, Memory)
- `_detect_language()` — определение языка (en/ru/mixed) по соотношению кириллицы/латиницы
- `_bilingual_route()` — разделение mixed-команд на русскую/английскую части с majority vote
- `_fuzzy_classify()` — typo-tolerant routing через `difflib.get_close_matches()` (только однословные ключи, см. §3)
- `_is_greeting()` — детекция приветствий с word boundaries (`\b` regex)
- Порядок роутинга: greeting → bilingual → exact_keyword → fuzzy → history → GENERAL

**server.py:**
- `normalize_user_input()` — очистка whitespace, каппинг повторяющихся символов, расширение русских аббревиатур (спс→спасибо, пж→пожалуйста, и т.д.)
- `_RU_TYPO_MAP` — фонетические подстановки (о→а, е→и, и т.д.)
- `_CMD_ALIASES` — 22 русские аббревиатуры
- System prompt: секция "UNDERSTANDING THE USER" о билингвальности

### 1.6 Unit Tests

**Файлы:** `tests/test_router.py`, `tests/test_normalize.py`

**test_router.py (65 tests):**
- `_detect_language`: en, ru, mixed, empty, punctuation, yo
- `_classify_by_keywords`: 5 agents EN + RU, greeting detection, priority order
- `_fuzzy_classify`: typo EN (implemnt), typo RU (архитект), только однословные ключи ("what" НЕ матчится к "what is")
- `_bilingual_route`: mixed commands, pure EN/RU→None
- `route_task`: full pipeline, history, greeting bypass, fallback GENERAL
- AgentType enum

**test_normalize.py (48 tests):**
- Whitespace: strip, collapse, tabs, newlines, empty
- Repeated chars: excessive, punctuation, mixed
- 22 Russian aliases + case preservation
- Phonetic substitution (здров→здрав→здравствуй)
- Mixed language, Unicode, numbers, idempotence

### 1.7 Bugfix: `__init__.py`

**Файл:** `orchestrator/agents/__init__.py`

- Исправлен импорт: `ARCHITECT_TOOLS` → `ARCHITECT_TOOLS_NAMES` (через `as` alias)
- Аналогично для CODER, REVIEWER, RESEARCHER, MEMORY

---

### 1.8 Model Fallback — автопереключение моделей (v1.0-beta)

**Файлы:** `analyze/_llm.py`, `analyze/_llm_async.py`, `orchestrator/server.py`

- Новый env `LLM_FALLBACK_MODELS` (через запятую) — цепочка запасных моделей после `LLM_MODEL`
- `_get_model_chain()` — строит приоритетный список: primary + fallbacks, модели без API-ключа пропускаются
- `llm_call`, `llm_acompletion`, `llm_astream`, `llm_completion_sync` — пробуют модели по очереди; фолбэк срабатывает при отказе (лимит, аутэдж), в стриминге — при открытии стрима
- Старт orchestrator логирует `Model chain: ... -> ...`
- Фикс в `_llm_async.py`: `openrouter/` проверяется ДО `"anthropic"` substring (как в sync-версии)

### 1.9 Brain-бэкенды — архитектура мозга FOL

**Файлы:** `fol/modules/llm/brain.py`, `fol/modules/llm/brain_router.py`, `fol/modules/llm/freebuff.py`, `fol/modules/llm/codebuff_adapter.py`

FOL поддерживает несколько brain-бэкендов через единую абстракцию `BrainInterface`:

| Бэкенд | Класс | Env | Статус |
|--------|-------|-----|--------|
| **current** | `CurrentLLMAdapter` | `FOL_BRAIN=current` | ✅ Рабочий (LiteLLM: OpenRouter/Ollama/MLX) |
| **freebuff** | `FreebuffBrainAdapter` | `FOL_BRAIN=freebuff` | ⚠️ Требует `FREEBUFF_API_URL` |
| **codebuff** | `CodebuffSDKBrainAdapter` | `FOL_BRAIN=codebuff` | ✅ Рабочий (через `@codebuff/sdk`) |

**`brain.py` — ядро:**
- `BrainInterface` — абстрактный контракт: `chat()`, `chat_stream()`, `acomplete()`, `classify()`, `plan()`, `select_tools()`, `summarize()`, `verify()`
- `CurrentLLMAdapter` — обёртка над `LiteLLMRouter`, передаёт `model=` и `api_key=` в каждый метод
- `FreebuffBrainAdapter` — placeholder; `available=False` до появления HTTP API Freebuff
- `get_brain(name)` — фабрика: возвращает `CurrentLLMAdapter` (default) или `CodebuffSDKBrainAdapter`

**`codebuff_adapter.py` — Codebuff SDK (новый):**
- Запускает Codebuff агентов через `npx codebuff run --json`
- Парсит streaming JSON-lines вывода
- Реализует `chat()`, `chat_stream()`, `acomplete()`
- Используется для переобучения мозга на основе базы знаний

**`brain_router.py` — роутинг с фолбэком:**
- `BrainRouter([brain1, brain2, ...])` — пробует бэкенды по очереди
- Автоматический fallback при ошибке
- Мониторинг здоровья бэкендов

**Активация:**
```bash
# По умолчанию (current)
FOL_BRAIN=current

# Codebuff SDK
FOL_BRAIN=codebuff
CODEBUFF_API_KEY=sk-...  # получить на codebuff.com/api-keys

# Freebuff (требует HTTP API)
FOL_BRAIN=freebuff
FREEBUFF_API_URL=http://localhost:3000/api/v1
FREEBUFF_API_TOKEN=...
```

### 1.10 Security-фиксы — Race Condition, Shell Injection, Memory Leak

**Файлы:** `fol/modules/tools/gate.py`, `fol/core/app.py`

**1. Race condition в ConfirmationGate:**
- `asyncio.Lock()` на `_pending` и `_approved` словари
- `_check_locked()` и `_approve_locked()` — внутренние методы без доп. блокировки
- `check()`, `approve()`, `revoke_expired()` — асинхронные с `async with self._lock:`
- Защита от конкурентных запросов в async-окружении

**2. Shell injection в `_extract_shell_command`:**
- `_DANGEROUS_CMD_PATTERNS` (frozenset) — 30+ опасных паттернов
- Блокирует: `rm -rf /`, `fork bomb`, `curl|sh`, `eval`, `python -c 'import os'`, `shutdown`, `mkfs`, `chmod 777 /`, `launchctl remove` и т.д.
- Regex-проверка pipe-to-shell: `curl ... | sh/bash/zsh/fish`
- Defense-in-depth (поверх ConfirmationGate Level 5)

**3. Memory leak в conversation history:**
- `_max_history = 100` — лимит хранимых диалогов
- `_record_turn()` обрезает историю через `self._conversation_history[-self._max_history:]`
- Защита от бесконечного роста памяти при долгих сессиях

**Результат тестирования:**
```
✅ fol/tests/: 1073/1073 passed
✅ Security tests: gate.py 92% coverage, app.py shell extraction: 39 tests
```

## 2. АРХИТЕКТУРА BILINGUAL ROUTING (v2 — исправленная)

```
Команда пользователя (напр. "review мой код")
    │
    ▼
_is_greeting()               ← шаг 0: приветствие?
    │                           'hello', 'как дела' → GENERAL (word boundary)
    │                           'hi' не матчится как 'this'
    ├── greeting → GENERAL
    └── нет → continue
    │
    ▼
_bilingual_route()          ← шаг 1: смешанный язык?
    │                           split на en + ru части
    │                           majority vote, при ничье → English
    │                           мин. 1 слово на часть (исправлено с 2→1)
    │
    ├── en/ru only → None
    └── mixed → AgentType
    │
    ▼
_classify_by_keywords()     ← шаг 2: точное совпадение
    │                           порядок: Architect→Reviewer→Coder→Researcher→Memory
    │                           REVIEWER теперь ПЕРЕД CODER (исправлено)
    │
    ├── совпадение → AgentType
    └── нет → None
    │
    ▼
_fuzzy_classify()           ← шаг 3: нечёткое совпадение (опечатки)
    │                           difflib.get_close_matches(cutoff=0.72)
    │                           каждое слово ≥3 букв проверяется
    │
    ├── совпадение → AgentType
    └── нет → None
    │
    ▼
route_task()                ← шаг 4: история разговора
    │                           проверяет последний ответ ассистента
    │
    ├── есть ключ → AgentType
    └── нет → GENERAL
```

### Ключевые слова агентов (примеры)

| Агент | EN | RU |
|-------|----|-----|
| **Architect** | architecture, design pattern, system design, roadmap | архитектур, спроектир, схема, тз |
| **Reviewer** | review, check, code review, audit, vulnerability | провер, ревью, качеств, аудит |
| **Coder** | implement, write code, pull request, refactor | напиш, код, создай, баг, тест |
| **Researcher** | search, find, what is, explain | найд, поищ, **ищи (fixed)**, гугл |
| **Memory** | remember, save, note, obsidian, remind | запомн, сохран, заметк, напомн |

---

## 3. ИСПРАВЛЕННЫЕ БАГИ (v1 → v2)

| Баг | Причина | Исправление |
|-----|---------|-------------|
| `'hi' in 'this' → True` | `_is_greeting` использовала `greeting in task_lower` | `\b` word boundary через `re.search` |
| `'ревью код' → CODER` | CODER был перед REVIEWER в _ROUTES | REVIEWER теперь перед CODER |
| `'как дела?' → CODER` | "дела" fuzzy-матчилась к "сделай" (CODER) | `_is_greeting` ловит "как дела" |
| `'ищи' → GENERAL` | "ищи" не fuzzy-матчился к "поищ" (0.57 < 0.72) | "ищи" добавлен как RESEARCHER keyword |
| `'check' в bilingual` | eng_part = 1 слово (<2) → skipped | мин. снижено с 2 до 1 |
| `'проверь код' → CODER` | CODER prio выше REVIEWER | REVIEWER теперь перед CODER |
| `'what do you think' → RESEARCHER` | "what" (4 буквы) fuzzy-матчился к multi-word ключу "what is" (ratio 0.727 > 0.72) | `_FUZZY_KEYWORDS` — только однословные ключи; multi-word ключи матчатся только exact substring-ом |

### Диагностика после исправлений

```
[OK] 'напиши код для сортировки' -> coder
[OK] 'спроектируй архитектуру' -> architect
[OK] 'проверь пул реквест' -> reviewer
[OK] 'найди информацию про AI' -> researcher
[OK] 'запомни это в obsidian' -> memory
[OK] 'ищи статью' -> researcher              ✓ (исправлено)
[OK] 'ревью код' -> reviewer                 ✓ (исправлено)
[OK] 'проверь мой код' -> reviewer           ✓ (исправлено)
[OK] 'implement sorting algorithm' -> coder
[OK] 'review the code' -> reviewer
[OK] 'search for AI papers' -> researcher
[OK] 'напиши код для sorting algorithm' -> coder
[OK] 'check мой код пожалуйста' -> reviewer  ✓ (исправлено)
[OK] 'как дела?' -> general                  ✓ (исправлено)
[OK] 'привет' -> general                     ✓ (исправлено)
[OK] 'hello' -> general
```

---

## 4. ТЕСТИРОВАНИЕ

```bash
# Запустить все тесты
python -m pytest tests/ -v

# Только билингвальный роутер
python -m pytest tests/test_router.py -v

# Только нормализация текста
python -m pytest tests/test_normalize.py -v

# Сборка SwiftUI приложения
cd fol-app && swift build

# Фильтры
python3 -m pytest tests/test_router.py -v -k "russian"      # русские тесты
python3 -m pytest tests/test_router.py -v -k "bilingual"    # bilingual тесты
python3 -m pytest tests/test_router.py -v -k "fuzzy"        # fuzzy matching
python3 -m pytest tests/test_normalize.py -v -k "russian"   # русские алиасы

# Python синтаксис
python3 -c "import ast; ast.parse(open('orchestrator/server.py').read())"
python3 -c "import ast; ast.parse(open('orchestrator/agents/router.py').read())"
```

### Результаты тестов (финальные)

```
✅ fol/tests/: 1073 passed           # полный прогон FOL тестов
✅ Swift build: Build complete         # fol-app сборка
✅ Brain tests: 130 passed             # brain, brain_router, freebuff_adapter, gate
✅ Shell command extract: 39 passed    # security patterns
✅ All diagnostics: pass
```

---

## 5. ИЗМЕНЁННЫЕ ФАЙЛЫ

| Файл | Изменение |
|------|-----------|
| `fol-app/Views/VoiceInputButton.swift` | Анимация пульсации, pulse ring, glow |
| `fol-app/Views/ChatInputBar.swift` | Physics waveform, shimmer/glow эффект |
| `fol-app/Views/ChatView.swift` | Плавные transition сообщений |
| `orchestrator/agents/router.py` | Русские ключевые слова, bilingual routing, fuzzy matching, greeting detection |
| `orchestrator/server.py` | normalize_user_input, typo map, system prompt bilingual |
| `orchestrator/agents/__init__.py` | Исправлен импорт _TOOLS → _TOOLS_NAMES |
| `tests/test_router.py` | 65 тестов для routing (НОВЫЙ ФАЙЛ) |
| `tests/test_normalize.py` | 48 тестов для normalize (НОВЫЙ ФАЙЛ) |
| `fol/modules/llm/brain.py` | BrainInterface — абстракция мозга, get_brain() фабрика |
| `fol/modules/llm/brain_router.py` | BrainRouter — роутинг с фолбэком по бэкендам |
| `fol/modules/llm/freebuff.py` | Конфигурация Freebuff Brain, FREEBUFF_REQUIREMENTS |
| `fol/modules/llm/codebuff_adapter.py` | CodebuffSDKBrainAdapter — мозг через Codebuff SDK (НОВЫЙ ФАЙЛ) |
| `fol/modules/tools/gate.py` | asyncio.Lock для thread-safe ConfirmationGate |
| `fol/core/app.py` | _DANGEROUS_CMD_PATTERNS + _max_history=100 (security + memory leak fix) |
| `CLAUDE.md` | Этот файл — единая документация |

---

## 6. КОМАНДЫ ДЛЯ РАЗРАБОТЧИКА

```bash
# === BUILD ===
cd fol-app && swift build           # Swift приложение
python3 -m pytest tests/ -v            # Python тесты

# === TEST SPECIFIC ===
python3 -m pytest tests/test_router.py -v -k "russian"      # русские тесты
python3 -m pytest tests/test_router.py -v -k "bilingual"    # bilingual тесты
python3 -m pytest tests/test_router.py -v -k "fuzzy"        # fuzzy matching
python3 -m pytest tests/test_normalize.py -v -k "russian"   # русские алиасы

# === RUN ===
cd fol-app && swift run             # Запустить приложение

# === SMOKE TEST ===
./setup/smoke-test.sh                  # Проверка всех сервисов

# === DEBUG ROUTER ===
python3 -c "
import sys; sys.path.insert(0, 'orchestrator')
from agents.router import route_task, _detect_language, _classify_by_keywords, _fuzzy_classify
text = 'напиши код для sorting algorithm'
print(f'Task: {text}')
print(f'Language: {_detect_language(text)}')
print(f'Keywords: {_classify_by_keywords(text)}')
print(f'Fuzzy: {_fuzzy_classify(text)}')
print(f'Route: {route_task(text)}')
"

# === DEBUG NORMALIZE ===
python3 -c "
import sys; sys.path.insert(0, 'orchestrator'); sys.path.insert(0, '.')
from orchestrator.server import normalize_user_input
tests = ['спс', 'пж помоги', 'здров', 'напиши sorting algorithm', 'noooo way!!!!!']
for t in tests:
    print(f'{t!r} -> {normalize_user_input(t)!r}')
"
```

---

## 7. ИЗВЕСТНЫЕ ОГРАНИЧЕНИЯ

1. **"what" → RESEARCHER — ИСПРАВЛЕНО.** Раньше `_fuzzy_classify` матчил короткое слово "what" к multi-word RESEARCHER ключу "what is" (`SequenceMatcher.ratio() = 0.727` > cutoff 0.72). Теперь fuzzy-matching работает только по однословным ключам (`_FUZZY_KEYWORDS`), а multi-word ключи ("what is", "write code") обрабатываются только exact substring-ом в `_classify_by_keywords`. Результат: `"what do you think" → GENERAL`, но `"what is machine learning" → RESEARCHER` (exact match).

   *Приемлемый trade-off:* typo без пробела "whatis machine learning" (0.923) больше НЕ фаззи-матчится к "what is" → GENERAL. Это осознанное следствие фикса — фаззи-матчинг работает только по словам, а не фразам.

2. **"check" → REVIEWER** — слово "check" как standalone keyword может быть слишком широким. "check the weather" → REVIEWER. Если это проблема, можно удалить "check" из REVIEWER и полагаться только на bilingual route.

3. **Фонетические подстановки** — корректно работают только для слов ≥4 букв. "прев" (3 буквы) не конвертируется в "привет".

4. **`test_normalize.py`** — требует установленных зависимостей FastAPI/LiteLLM (иначе весь файл skip).

5. **"pull request" → REVIEWER, не CODER** — с новым порядком `review this pull request` → REVIEWER (из-за "review"), а не CODER. Для CODER используйте "create a pull request" или "code change".

---

## 8. ВЫПОЛНЕННЫЕ КОМАНДЫ ИЗ CLAUDE.md

```
✓ python3 -m pytest tests/ -v                    -> 1073 passed (FOL)
✓ python3 -m pytest tests/test_router.py -v       -> 65 passed
✓ python3 -m pytest tests/test_normalize.py -v    -> 48 passed
✓ tests/test_router.py -k "russian"               -> 22 passed
✓ tests/test_router.py -k "bilingual"             -> 7 passed
✓ tests/test_router.py -k "fuzzy"                 -> 8 passed
✓ tests/test_normalize.py -k "russian"            -> 25 passed
✓ cd fol-app && swift build                    -> Build complete (45s)
✓ python3 -c "ast.parse(open('server.py'))"       -> server.py: OK
✓ python3 -c "ast.parse(open('router.py'))"       -> router.py: OK
✓ python3 -c "ast.parse(open('fol/core/app.py'))" -> app.py: OK (shell injection fix)
✓ Router diagnostics                              -> All 18 tests pass
✓ normalize_user_input diagnostics                -> спс->спасибо, пж->пожалуйста и т.д.
✓ Brain tests (brain + router + freebuff + gate) -> 130 passed
✓ Security tests (shell extraction)              -> 39 passed
```
