# FOL — Персональный AI-ассистент (JARVIS для macOS)

> **Статус: v1.0.0** — стабильный релиз, 989+ тестов, 5 сценариев ежедневного использования работают от начала до конца.

**Единый проект** — FOL: Python AI-ядро + SwiftUI macOS приложение.

## Что это

FOL — **цифровой двойник**, AI-ассистент, который:
- 🖥️ Живёт на **MacBook** в вырезе (Notch UI)
- 🧠 Имеет **JARVIS-подобные** возможности (голос, зрение, память, инструменты)
- 🔄 Понимает **контекст** экрана, почты, календаря
- 📝 Пишет в **живую память** (Obsidian + episodic)
- 🤖 **Агентный цикл**: сам выбирает инструменты, выполняет, проверяет результат

## Рабочие сценарии (проверено end-to-end)

| Сценарий | Как работает |
|---|---|
| «Открой Safari и найди новости об OpenAI» | открывает Safari → ищет → возвращает сводку |
| «Напиши письмо преподавателю» | спрашивает контакт / использует Google OAuth |
| «Создай событие в календаре» | `create_event` через Google Calendar |
| «Открой проект FOL» | Finder + клавиатурные команды |
| «Запомни, что завтра отправить отчёт» | `save_to_obsidian` → живая память |

## Быстрый старт

```bash
# 1. Настрой LLM в .env (см. раздел «LLM» ниже)
cp .env.example .env   # или отредактируй существующий .env

# 2. Установи зависимости
pip install -r requirements.txt

# 3. Запусти все сервисы
./run_all.sh

# 4. Или по отдельности:
./run_all.sh orchestrator   # AI сервер (порт 8420)
./run_all.sh agent          # Десктоп-контроль (порт 8421)
./run_all.sh fol            # FOL API с JARVIS-командами (порт 8754)
./run_all.sh swift          # SwiftUI macOS приложение
```

## LLM — настройка через .env

Всё работает через **LiteLLM** — одна строка меняет модель:

```env
# Бесплатно (OpenRouter free-модели, 120B — отлично для tool calling)
LLM_MODEL=openrouter/nvidia/nemotron-3-super-120b-a12b:free
OPENROUTER_API_KEY=sk-or-v1-...

# Или локально (Ollama) — без API, но слабее для 50 инструментов
LLM_MODEL=ollama/llama3.2:3b

# Или платно (после пополнения кредитов)
LLM_MODEL=openai/gpt-4o-mini
OPENAI_API_KEY=sk-proj-...

# Лимит токенов ответа (учитывай баланс провайдера)
LLM_MAX_TOKENS=1500

# Фолбэк: если основная модель недоступна (лимит/аутэдж) — пробуем по очереди
LLM_FALLBACK_MODELS=ollama/llama3.2:3b
```

**Автопереключение моделей.** Если основная модель недоступна (исчерпан бесплатный лимит, аутэдж провайдера, ошибка API), ассистент автоматически пробует модели из `LLM_FALLBACK_MODELS` по порядку. Модели без настроенного API-ключа пропускаются, поэтому система работает, пока доступна хотя бы одна модель. Цепочка логируется на старте: `Model chain: ... -> ...`.

**Ключевое преимущество — двухэтапный выбор инструментов.** Модель никогда не видит все 50 инструментов сразу: сначала запрос классифицируется (email/calendar/memory/web/coding/desktop), и модель получает только 5–12 релевантных. Поэтому даже 3B-модель выбирает инструменты правильно, а 120B — работает идеально.

## Архитектура

```
Пользователь (Notch UI / Web / Голос)
      │
      ▼
Orchestrator (FastAPI, :8420)
      │   роутер агентов (General/Architect/Coder/Reviewer/Researcher/Memory)
      │   двухэтапный выбор инструментов (категория → 5-12)
      │   loop guard (защита от зацикливания)
      ▼
LLM (LiteLLM: OpenRouter / Ollama / OpenAI)
      │   tool calls
      ▼
Execution: Agent Server (:8421) · Productivity (Gmail/Calendar) · Obsidian · FOL (:8754)
      │
      ▼
Результат возвращается в LLM → финальный ответ (SSE-стриминг в UI)
```

## Структура проекта

```
SecondSelf/
├── SecondSelf/              # SwiftUI macOS приложение (Notch UI, голос, анимации)
├── orchestrator/            # FastAPI AI-сервер (порт 8420) — агенты, tools, память
│   ├── agents/              # General/Architect/Coder/Reviewer/Researcher/Memory + роутер
│   └── productivity_tools.py# Gmail, Calendar, Docs, web search
├── agent-server/            # Десктоп/браузер контроль (порт 8421)
├── fol/                     # Python AI-ядро FOL (порт 8754)
├── src/                     # Next.js web интерфейс (SSE-чат)
├── auth/                    # Google OAuth (Gmail/Calendar)
├── fetch/                   # Gmail, Tavily, Calendar fetch
├── analyze/                 # LLM-слой, анализ (voice, behavior, topics)
├── obsidian/                # Живая память (vault, linker, tools)
├── context_engine/          # Контекст экрана (активное приложение, URL)
├── utils/                   # episodic_writer, daily_tracker, text_normalizer
├── cookie_sync/             # Перенос cookies Chrome в агент-браузер
├── tests/                   # 989+ тестов
├── scripts/
│   ├── verify_scenarios.sh  # Авто-проверка 5 сценариев
│   └── demo.sh              # Гарнесс для записи видео-демо
├── Dockerfile / docker-compose.yml / .github/workflows/
└── run_all.sh               # Единый лаунчер
```

## Демо (для записи видео)

```bash
./scripts/demo.sh              # 5 сценариев с паузами для нарезки
DEMO_PAUSE=5 ./scripts/demo.sh # короткие паузы
DEMO_QUICK=1 ./scripts/demo.sh # без пауз (проверка)
```

Сценарии демо: «Open Safari» → «Find the latest OpenAI news» → «Remember I need to send the report tomorrow» → «Open the FOL project» → «Create a calendar event».

## Качество

- **989+ тестов** (`python3 -m pytest tests/ -v`) — роутер, нормализация, память, инструменты, SSE, loop guard, фолбэк моделей, response formatter
- **Loop guard**: агент не может зациклиться — повторный вызов инструмента N раз прерывается с валидной историей
- **Memory**: identity.md / preferences.md / episodic.md + Obsidian + daily tracker
- **CI**: `.github/workflows/test.yml` — pytest + Swift build на каждый push

## Порты

| Порт | Сервис | Описание |
|------|--------|----------|
| 8420 | Orchestrator | Главный AI-сервер (SSE /chat) |
| 8421 | Agent Server | Десктоп/браузер контроль |
| 8754 | FOL API | JARVIS-команды |
| 3000 | Next.js | Web интерфейс |
| 11434 | Ollama | Локальный LLM (опционально) |

## Документация

- **`CHANGELOG.md`** — история версий (текущая: **v1.0.0**)
- **`MERGED_README.md`** — полная документация о слиянии проектов
- **`FOL_UPGRADE.md`** — мастер-документ архитектуры
- **`CLAUDE.md`** — контекст для AI-модели
- **`DESIGN.md`** — дизайн-система
