# FOL — Персональный AI-ассистент для macOS (JARVIS)

> **v1.0.0** — рабочий, протестированный релиз: **2049+ тестов зелёные**, E2E 14/14, macOS-приложение собирается.

FOL — **цифровой двойник**: AI-ассистент, который живёт в вырезе MacBook (Notch UI),
понимает контекст экрана, помнит о вас и выполняет действия на компьютере.

**Проблема, которую решает FOL:** повседневная работа за компьютером состоит из
повторяющихся действий, повторного объяснения контекста и постоянного переключения
между приложениями — это и есть «трение» (friction), которое отнимает время.

**Решение — три направления:**

| Направление | Что даёт |
|---|---|
| **1. Desktop automation** | Пользователь не тратит время на повторяющиеся действия в macOS — FOL открывает приложения, ищет в браузере, работает с файлами и кликами |
| **2. Context + Memory** | FOL помнит контекст и предпочтения — не нужно постоянно объяснять одно и то же |
| **3. Proactive assistance** | FOL сам замечает полезный контекст и предлагает действие, не дожидаясь команды |

---

## Быстрый старт

```bash
# 1. Настройте .env (см. .env.example — ключи пустые, безопасно)
cp .env.example .env

# 2. Установите зависимости
pip install -r requirements.txt

# 3. Запустите все сервисы
./run_all.sh

# 4. Проверьте
curl http://localhost:8420/status     # Orchestrator
curl http://localhost:8421/health     # Agent Server (десктоп-контроль)
curl http://localhost:8754/health     # FOL API (JARVIS-команды)
```

Запуск по отдельности: `./run_all.sh orchestrator | agent | fol | swift | web`.

### LLM — одна строка в `.env`

```env
LLM_MODEL=ollama/llama3.2:3b                          # локально, бесплатно
# или LLM_MODEL=openrouter/nvidia/nemotron-3-super-120b-a12b:free
LLM_FALLBACK_MODELS=ollama/llama3.2:3b                # автопереключение при сбое
```

Если основная модель недоступна (квота/аутэдж), ассистент автоматически пробует
модели из `LLM_FALLBACK_MODELS` по очереди — система работает, пока доступна хотя
бы одна модель.

### Локально через Ollama (бесплатно, без API-ключей)

```bash
brew install ollama
ollama serve &                    # или: brew services start ollama
ollama pull llama3.2:3b           # ~2 GB, одна команда
```

Затем в `.env`: `LLM_MODEL=ollama/llama3.2:3b`. Это рекомендуемый способ для
первого запуска — никакие платные ключи не нужны.

---

## Демо-сценарии (проверены end-to-end)

```bash
./scripts/demo.sh                  # 5 сценариев с паузами для записи видео
DEMO_QUICK=1 ./scripts/demo.sh     # без пауз (проверка)
./scripts/verify_scenarios.sh      # авто-проверка сценариев
python3 scripts/e2e_check.py       # E2E: сервисы + health + MJPEG + SSE
```

| Сценарий | Как работает |
|---|---|
| «Открой Safari и найди новости об OpenAI» | открывает Safari → ищет → сводка |
| «Напиши письмо преподавателю» | контакт / Google OAuth |
| «Создай событие в календаре» | `create_event` через Google Calendar |
| «Открой проект FOL» | Finder + клавиатурные команды |
| «Запомни, что завтра отправить отчёт» | `save_to_obsidian` → живая память |

---

## Архитектура

```
Пользователь (Notch UI / Web / Голос)
      │
      ▼
Orchestrator (FastAPI, :8420)
      │   роутер 6 агентов (General/Architect/Coder/Reviewer/Researcher/Memory)
      │   двухэтапный выбор инструментов (категория → 5-12 из 50)
      │   loop guard (защита от зацикливания)
      ▼
LLM (LiteLLM: OpenRouter / Ollama / OpenAI) — фолбэк-цепочка моделей
      │   tool calls
      ▼
Execution: Agent Server (:8421, десктоп/браузер) · Productivity (Gmail/Calendar)
           · Obsidian (память) · FOL API (:8754, JARVIS)
      │
      ▼
Результат → LLM → финальный ответ (SSE-стриминг в UI)
```

Ключевые механизмы:
- **ToolRegistry** (`fol/modules/tools/registry.py`) — единый реестр всех 50 инструментов: схема, риск, подтверждение.
- **ConfirmationGate** (`fol/modules/tools/gate.py`) — код решает, никогда модель: опасные действия блокируются до подтверждения пользователя, подтверждение привязано к точной сигнатуре вызова.
- **Двухэтапный выбор инструментов** — модель видит 5–12 релевантных инструментов, а не все 50.
- **Loop guard** — повторный одинаковый вызов N раз прерывается.
- **Memory** — identity / preferences / episodic + Obsidian vault + daily tracker; контекст внедряется в каждый запрос LLM.
- **Proactive Mode** — `suggestion_engine` (profile/pattern/ambient) + ambient-цикл 30с + переключатель `proactive on/off` в FOL API.
- **Безопасность** — `.env` не отслеживается Git, секреты вычищаются из логов и дашборда, неизвестные инструменты отклоняются (fail closed).

## Структура проекта

```
fol/                       # Python AI-ядро FOL (JARVIS API :8754)
  ├── core/ modules/ api/ config/ plugins/ tests/
orchestrator/              # FastAPI AI-сервер (:8420): агенты, tools, память
agent-server/              # Десктоп/браузер контроль (:8421)
SecondSelf/                # SwiftUI macOS приложение (Notch UI, голос)
src/                       # Next.js web интерфейс (SSE-чат)
auth/ fetch/ analyze/ clean/ utils/ context_engine/ obsidian/ dashboard/
cookie_sync/ bridge/ setup/ scripts/ tests/ docs/
run_all.sh                 # Единый лаунчер всех сервисов
```

## Порты

| Порт | Сервис |
|------|--------|
| 8420 | Orchestrator (AI-сервер, SSE) |
| 8421 | Agent Server (десктоп/браузер) |
| 8754 | FOL API (JARVIS-команды) |
| 3000 | Next.js web |
| 11434 | Ollama (локальный LLM, опционально) |

## Качество

- **2049+ тестов, 0 падений** — `python3 -m pytest tests/` (1168), `python3 -m pytest fol/tests/` (810), orchestrator-local (71)
- **E2E 14/14** — `python3 scripts/e2e_check.py` (сервисы, health, MJPEG, SSE, без утечек tool-call)
- **macOS-сборка** — `cd SecondSelf && swift build` ✓, `./build-app.sh` → `build/Second Self.app`
- CI: `.github/workflows/test.yml` (pytest + синтаксис + Swift build)

## Безопасность (перед шиппингом)

- Неизвестные инструменты → fail closed (`GateDecision.REJECT`)
- Опасные инструменты → подтверждение пользователя, привязанное к аргументам
- Модель не может подтвердить сама себя — решает код
- Shell-подобные `fol_command` → всегда подтверждение
- Секреты не попадают в память/логи/дашборд; API-ключи не коммитятся (`.gitignore`)

## Лицензия

MIT — см. [LICENSE](LICENSE).
