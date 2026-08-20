# FOL — Полное описание проекта

> Документ: 2026-08-17 · Версия: 1.1.0
> Краткая версия: [`README.md`](../README.md) · Архитектура: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) · План: [`FOL_UPGRADE.md`](../FOL_UPGRADE.md)

---

## 1. Что такое FOL

**FOL — персональный AI-ассистент для macOS в духе JARVIS.** Это цифровой двойник
пользователя: приложение живёт в вырезе MacBook (Notch UI), видит контекст экрана,
помнит о пользователе и выполняет действия на компьютере.

**Проблема, которую решает FOL:** повседневная работа за компьютером состоит из
повторяющихся действий, повторного объяснения контекста и постоянного переключения
между приложениями — это «трение» (friction), отнимающее время.

**Три направления:**

| Направление | Что даёт |
|---|---|
| **1. Desktop automation** | FOL открывает приложения, ищет в браузере, работает с файлами, кликами и клавиатурой — пользователь не тратит время на рутину |
| **2. Context + Memory** | FOL помнит контекст и предпочтения (Obsidian-память, консолидация дневных логов) — не нужно объяснять одно и то же |
| **3. Proactive assistance** | FOL сам замечает полезный контекст и предлагает действие, не дожидаясь команды |

Исторически проект назывался **Second Self**; начиная с версии 1.1.0 продукт
полностью переименован в **FOL** (папка SwiftUI-приложения — `fol-app/`, бинарник и
модуль — `FOL`).

---

## 2. Архитектура

FOL — это связка трёх локальных Python-сервисов и нативного macOS-приложения:

```
Пользователь (Notch UI / Web / Голос)
      │
      ▼
Orchestrator (FastAPI, :8420)          ← AI-сервер, SSE-стриминг
      │   6 агентов · билингвальный роутинг (RU+EN)
      │   двухэтапный выбор инструментов · loop guard
      ▼
BrainInterface → LiteLLMRouter         ← единая абстракция рассуждений
      │   (cloud-only: OpenRouter / OpenAI / Anthropic / …) + фолбэк-цепочка
      │   tool calls
      ▼
ToolRegistry → ConfirmationGate        ← риск-гейт (5 уровней, код решает)
      │
      ▼
Execution: Agent Server (:8421, десктоп/браузер)
         · Productivity (Gmail/Calendar)
         · Obsidian (память)
         · FOL API (:8754, JARVIS-команды)
      │
      ▼
Результат → LLM → финальный ответ (SSE в UI, санитизированный formatter'ом)
```

### Порты

| Порт | Сервис |
|------|--------|
| 8420 | Orchestrator — AI-сервер, SSE-чат, агенты |
| 8421 | Agent Server — выполнение десктоп/браузер действий |
| 8754 | FOL API — JARVIS-команды, health, локальный STT |
| 3000 | Next.js web-интерфейс |
| ~~11434~~ | ~~Ollama — локальный LLM~~ — удалён политикой (без локальных ИИ) |

---

## 3. Компоненты

### 3.1 FOL-ядро (`fol/`) — Python AI-движок

Каноническое ядро всех возможностей. Модули:

| Модуль | Назначение |
|---|---|
| `fol/modules/llm/` | Рассуждения: `brain.py` (BrainInterface), `router.py`/`model_router.py` (LiteLLM), `agent.py`, `personality.py`, `proactive.py`, `prompt_manager.py`, `function_calling.py`, `behavioral_learner.py`, `memory_enhancer.py`, `tokenizer.py`, `language.py` |
| `fol/modules/tools/` | Инструменты: `registry.py` (ToolRegistry — единый реестр всех инструментов), `gate.py` (ConfirmationGate + 5-уровневый RiskScorer), `automation/`, `browser/`, `desktop/`, `mouse_keyboard/`, `system/` |
| `fol/modules/input/` | Ввод: `context.py` (единый контекстный движок: активное приложение, URL браузера, скриншот + Vision OCR), `voice/` (локальный STT: mlx-whisper, speech_recognition), `speech.py`, `screen_capture.py`, `vision.py`, `text_input.py` |
| `fol/modules/output/` | Вывод: `tts.py` (голос JARVIS), `notifications.py`, `clipboard_out.py`, `display.py`, `telegram.py` |
| `fol/modules/memory/` | Память: `obsidian.py`, `brain.py`, `rag.py` (векторный поиск), `consolidation.py` + `scheduler.py` (LLM-синтез дневных логов), `conversation.py`, `episodic_memory.py`, `knowledge_graph.py`, `identity/`, `preferences.py`, `sql_store.py`, `vector_store.py`, `long_term.py` |
| `fol/core/` | Ядро: `app.py` (главный класс FOL, `_extract_shell_command`, режимы работы), `lifecycle.py` |
| `fol/api/` | REST API (`rest/server.py`), FOL web-интерфейс |

### 3.2 Orchestrator (`orchestrator/`) — AI-сервер :8420

- **6 агентов** (`orchestrator/agents/`): General, Architect, Coder, Reviewer, Researcher, Memory
- **Билингвальный роутинг** (`agents/router.py`): определение языка (RU/EN/mixed),
  точное совпадение ключевых слов, typo-tolerant fuzzy-матчинг
  (`difflib.get_close_matches`), детекция приветствий, роутинг по истории разговора
- **Нормализация ввода** (`server.py`): очистка whitespace, каппинг повторяющихся
  символов, расширение русских аббревиатур (спс→спасибо), фонетические подстановки
- **Двухэтапный выбор инструментов**: модель получает 5–12 релевантных
  инструментов (категория задачи → узкий набор), а не все 50
- **Loop guard**: повторный одинаковый tool-call N раз подряд прерывается
- **Response Formatter** (`response_formatter.py`): санитизация вывода — инструменты,
  JSON и имена tool-ов никогда не попадают в чат; SSE-тип `activity`
- **Suggestion Engine** (`suggestion_engine.py`): proactive-предложения
  (profile / pattern / ambient)
- **LLM Bridge** (`llm_bridge.py`): совместимый слой, делегирует в
  `get_brain("current")` (BrainInterface)

### 3.3 Agent Server (`agent-server/`) — десктоп/браузер :8421

Выполняет действия на macOS: открытие/закрытие приложений, клики, перетаскивание,
ввод текста, горячие клавиши, буфер обмена, скриншоты (MJPEG-поток для VNC PiP),
уведомления, управление браузером через Chrome CDP (:9222) и AppleScript (Safari/Arc/Edge/Firefox).

### 3.4 macOS-приложение (`fol-app/`) — SwiftUI

- **Notch UI**: панель в вырезе MacBook, чат, статусы, JARVIS-анимации
- **SSE-чат**: стриминг ответов, tool-call пилюли, санитизированные activity-статусы
- **A2UI-карточки** (`Views/`): `ActionInfoCard`, `PeekNotificationBadge`,
  `RiskConfirmCard`, `StrictModalCard`, `ConfirmActionView`, `TaskApprovalView` —
  интерфейс риск-гейта (уровни 3–5)
- **Голос**: кнопка с пульсацией (`VoiceInputButton`), физическая симуляция волн
  (`AudioWaveformView`), hold-to-talk запись
- **STT**: OpenAI Whisper → ElevenLabs Scribe → **локальный mlx-whisper**
  (`LocalSTTService`, `POST :8754/api/stt`) — микрофон работает без облачных ключей
- **TTS**: голос JARVIS, прерывание речи при новом сообщении
- **VNC PiP**: встроенное видео десктопа агента (`VNCPipView`)
- **Меню-бар**: status item, статус-логи событий (chat opened, message sent…)
- **Управление сервисами**: при старте проверяет порты 8420/8421/8754 и запускает
  только недостающие (не убивает живые)

### 3.5 Web (`src/`) — Next.js

SSE-чат через `POST /api/chat/stream` → orchestrator:8420, потоковая отрисовка
токенов, tool-call пилюли, состояния thinking/working/complete. Отмечен как legacy
(`docs/ARCHITECTURE.md`): новые фичи сюда не добавляются.

### 3.6 Память — Obsidian Brain

- **Obsidian v5** (`obsidian/`): клиент Local REST API 5.0.2 — `write_note` (JSON
  body), `search`, `list_notes`, `get_tags`, `move_note`, `append_to_note`,
  `execute_command`; PATCH с фолбэком «read → modify → write»
- **Vault bootstrap**: `init_vault()` (папки + `_index.md` + шаблоны + `Profile.md`),
  `refresh_indices()`, шаблоны заметок project/idea/decision/knowledge/daily
- **Файлы памяти**: `~/.secondself/{identity,preferences,episodic}.md` + Obsidian vault
- **Консолидация** (`fol/modules/memory/consolidation.py`): фоновый LLM-синтез
  дневных Work-Log → `Lessons.md` + `Daily-Consolidated/YYYY-MM-DD.md`

### 3.7 Контекст — единый контекстный движок

`fol/modules/input/context.py` (ContextEngine/ContextSnapshot) — канонический
источник десктоп-контекста: активное приложение (AppleScript), URL и заголовок
вкладки браузера, скриншот + Vision OCR (по запросу), список запущенных приложений.
`context_engine/` на корне — compatibility shim (lazy-импорт, PEP 562 re-export).

---

## 4. Ключевые механизмы

### 4.1 5-уровневый RiskScorer (код решает, не модель)

`fol/modules/tools/gate.py` — детерминированная оценка риска каждого вызова
инструмента на runtime. Модель не может её обойти.

| Уровень | `RiskLevel5` | `GateDecision` | UI-поведение |
|---|---|---|---|
| 1 | `SAFE_READ` (чтение, поиск, скриншоты) | `OK` | выполняется молча |
| 2 | `UI_NAVIGATION` (открытие приложений, навигация) | `OK` | выполняется молча |
| 3 | `INTERACTIVE_GUI` (клики, ввод текста, hotkey) | `PEEK_CONFIRM` | лёгкое auto-dismiss уведомление |
| 4 | `FILE_MUTATION` (запись файлов, email, события, память) | `CONFIRM` | A2UI-карточка — блок до подтверждения |
| 5 | `SYSTEM_DANGEROUS` (`execute_command`, shell) | `STRICT_CONFIRM` | модалка: точная сигнатура + таймаут |

Неизвестные инструменты → `REJECT` (fail-closed, никогда не выполняются).
Подтверждение привязано к точной сигнатуре вызова; модель не может подтвердить сама себя.

### 4.2 BrainInterface — единая абстракция рассуждений

`fol/modules/llm/brain.py` — единый провайдер-независимый контракт:
`chat / chat_stream / acomplete / classify / plan / select_tools / summarize / verify`.
Бэкенд выбирается через `FOL_BRAIN`:
- `current` (по умолчанию) — `CurrentLLMAdapter` поверх `LiteLLMRouter`
  (cloud-only: OpenRouter/OpenAI/Anthropic/…) — рабочий рантайм; локальные
  провайдеры (Ollama/MLX) исключены политикой;
- `freebuff` — честно отклоняется (`BrainConfigurationError`): у Freebuff нет
  программного интерфейса, молчаливого фолбэка нет.

Оркестратор (llm_bridge, memory_bridge, suggestion_engine) делегирует через
`get_brain("current")`. Память намеренно вне интерфейса: brain рассуждает,
MemoryService (Obsidian) хранит.

### 4.3 Билингвальный роутинг (RU + EN)

`orchestrator/agents/router.py`:
1. `_is_greeting()` — приветствия с word boundaries («hi» не матчится в «this»)
2. `_bilingual_route()` — смешанные команды: split на RU/EN части, majority vote
3. `_classify_by_keywords()` — точное совпадение (Architect→Reviewer→Coder→Researcher→Memory)
4. `_fuzzy_classify()` — typo-tolerant через `difflib` (cutoff 0.72, только однословные ключи)
5. `route_task()` — история разговора → GENERAL

Плюс `normalize_user_input()`: аббревиатуры (спс→спасибо, пж→пожалуйста),
фонетические подстановки, каппинг повторяющихся символов.

### 4.4 Фолбэк-цепочка моделей

`LLM_FALLBACK_MODELS` (через запятую) — если `LLM_MODEL` недоступна (квота, аутэдж,
пустой ответ), ассистент пробует модели по очереди (sync/async/stream). Модели без
API-ключа пропускаются; цепочка логируется на старте (`Model chain: ...`).

### 4.5 Голос (STT + TTS)

- **STT**: OpenAI Whisper → ElevenLabs Scribe → локальный mlx-whisper
  (`fol/modules/input/voice/providers/mlx_whisper.py`, Apple Silicon, офлайн).
  При отсутствии mlx-whisper — понятная ошибка установки, а не «ничего не услышано»
- **TTS** (`fol/modules/output/tts.py`): голос JARVIS; отправка сообщения/запись
  прерывают речь

### 4.6 Режимы работы

`fol/core/app.py` — переключение голосом или текстом («FOL, режим фокус»):
- **Companion** (по умолчанию) — обычное общение
- **Assistant** — задачи на Mac напрямую
- **Agent** — сложные многошаговые задачи
- **Focus** — минимум разговоров, максимум действий

Режим передаётся в контекст LLM (`CURRENT MODE: …`), виден в `status`/`_help`.
Поддержаны wake-word («FOL, …»), вежливая форма, падежи, EN/RU.

### 4.7 Контекст разговора (follow-up)

`ContextManager.is_follow_up()` детектит продолжения («Найди новости про OpenAI» →
«А какая из них самая важная?»), `get_current_topic()` извлекает сущности из
истории, блок привязки внедряется в промпт — модель резолвит местоимения.

### 4.8 Shell-команды

`_extract_shell_command` (`fol/core/app.py`): матчит самый длинный префикс первым
(«выполни команду pwd» → `pwd`, а не «команду pwd»), снимает хвостовой мусор и
предложенную пунктуацию.

### 4.9 Proactive Mode

`suggestion_engine` (profile/pattern/ambient) + ambient-цикл 30с + переключатель
`proactive on/off` в FOL API. FOL сам предлагает действие на основе профиля,
паттернов и текущего контекста.

---

## 5. Безопасность

- Неизвестные инструменты → `REJECT` (fail-closed)
- 5-уровневый риск-гейт: опасные действия блокируются до подтверждения пользователя
- Подтверждение привязано к точной сигнатуре вызова (аргументы)
- Модель не может подтвердить сама себя — решает код
- Shell-подобные `fol_command` → всегда подтверждение
- Секреты вычищаются из логов/памяти/дашборда; `.env*` не коммитятся
  (`.gitignore`); шаблоны коммитятся с пустыми ключами
- `codesign`/ad-hoc подпись .app, `xattr -cr` перед сборкой; postinstall снимает
  Gatekeeper quarantine

---

## 6. Сборка и релиз

```bash
./build-app.sh                        # → build/FOL.app (SwiftUI, подписан ad-hoc или Developer ID)
./build-pkg.sh                        # → build/FOL-<VERSION>.pkg (установщик + Python-бэкенд)
sudo installer -pkg build/FOL-1.1.0.pkg -target /   # установка
bash update.sh                        # обновление с прошлой версии (одной командой)
./scripts/sign-and-notarize.sh --wait # Developer ID подпись + нотаризация + стаплинг
```

- Версия берётся из `VERSION` (сейчас `1.1.0`), история — `CHANGELOG.md`
- Пакет ставит: `/Applications/FOL.app` + `/usr/local/share/second-self/` (бэкенд)
  + postinstall (зависимости, `.env`, Gatekeeper)
- CI: `.github/workflows/test.yml` (pytest + синтаксис + Swift build),
  `.github/workflows/release.yml` (релизный пайплайн)

---

## 7. Тестирование

```bash
python3 -m pytest tests/ -v            # корневые тесты (роутер, normalize, e2e-моки, …)
python3 -m pytest fol/tests/ -v        # тесты FOL-ядра (модули, риск-гейт, brain, voice…)
cd fol-app && swift build              # сборка SwiftUI
./scripts/e2e_check.py                 # E2E: сервисы + health + MJPEG + SSE
```

По данным README: **2049+ тестов** (1168 корневых + 810 FOL + 71 orchestrator-local),
E2E 14/14. Новые наборы 1.1.0: риск-гейт, brain, контекст-движок, voice, консолидация,
качество ответов, chaos agent-server, интеграции (ToolRegistry/LLM-bridge/web-tier/
safety-audit/final-response).

---

## 8. Структура проекта

```
fol/                       # Python AI-ядро FOL (модули llm/tools/input/output/memory)
fol-app/                   # SwiftUI macOS приложение (Notch UI, голос, A2UI)
orchestrator/              # FastAPI AI-сервер :8420 (агенты, роутинг, память, SSE)
agent-server/              # Десктоп/браузер контроль :8421
src/                       # Next.js web-интерфейс (legacy)
obsidian/                  # Obsidian Brain v5 (живая память)
context_engine/            # Compatibility shim → fol/modules/input/context.py
auth/ fetch/ analyze/ clean/ utils/ cookie_sync/ bridge/ dashboard/
setup/ scripts/ tests/ docs/
build/ Release/            # Артефакты: FOL.app, FOL-<ver>.pkg (+ sha256)
run_all.sh                 # Единый лаунчер всех сервисов
update.sh                  # Обновление одной командой
VERSION CHANGELOG.md       # Версия и история
```

---

## 9. Быстрый старт

```bash
cp .env.example .env        # ключи пустые — безопасно
pip install -r requirements.txt
./run_all.sh                # все сервисы
curl http://localhost:8420/status   # Orchestrator
curl http://localhost:8421/health   # Agent Server
curl http://localhost:8754/health   # FOL API
```

LLM — одна строка в `.env` (только API-провайдеры, без локальных моделей):

```env
LLM_MODEL=openrouter/deepseek/deepseek-v3            # API, без локального инференса
LLM_FALLBACK_MODELS=openai/gpt-4o-mini,anthropic/claude-sonnet-4  # автопереключение при сбое
```

---

## 10. Дорожная карта

`ROADMAP_5_FEATURES.md` (5 крупных фич, порядок по зависимостям):

1. **Self-analysis** — самоанализ (база для остальных)
2. **Multi-Agent System** — расширение с 6 до 8+ агентов
3. **Voice Engine** — TTS+STT (независим, нужен для Mobile)
4. **Plugin System + Modes** — режимы фильтруют агентов
5. **Mobile Companion** — зависит от WebSocket bridge + Voice Engine

---

## 11. Лицензия

MIT — см. [LICENSE](../LICENSE).
  