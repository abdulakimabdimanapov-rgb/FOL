# FOL — Your Smart Helper for Mac

> **v1.3.0** — Free AI brain, key rotation, bilingual (Русский + English), Obsidian memory, 1073+ tests.

**FOL** is a smart assistant that lives on your MacBook. It helps you with your computer. It can open apps, find files, talk to you, and remember things.

You can talk to it in **Russian** or **English**.

---

## What Can FOL Do? / Что умеет FOL?

| Feature | What It Does | На русском |
|---------|-------------|------------|
| **Chat** | Talk to FOL. Get answers in real time. | Чат с ИИ |
| **Voice** | Press the microphone, speak. FOL writes what you say. | Голосовой ввод |
| **Screen** | FOL sees your screen. It can take screenshots. | Видит экран |
| **Apps** | FOL opens apps, clicks, types for you. | Управление приложениями |
| **Browser** | FOL goes to websites, clicks links, scrolls pages. | Управление браузером |
| **Memory** | FOL remembers your name, preferences, talks. | Память |
| **Agents** | 5 special helpers: Architect, Coder, Reviewer, Researcher, Memory. | Агенты |
| **Safety** | Dangerous actions need your permission. | Безопасность |
| **Two Languages** | Works in Russian and English. Even mixed! | Два языка |
| **Typo Fix** | If you make a mistake in typing, FOL still understands. | Исправление опечаток |

---

## How Does It Work? / Как это работает?

FOL has **3 parts**:

```
You → Talk to FOL → FOL thinks → FOL does things on your computer
```

### 1. API Server (port 8754)
This is the main part. It receives your messages and sends answers.

### 2. Orchestrator (port 8420)
This is the "brain". It talks to the AI model (like ChatGPT) and decides what to do.

### 3. Agent Server (port 8421)
This part controls your computer. It opens apps, clicks, takes screenshots.

### Ports (порты)

| Port | What | На русском |
|------|------|------------|
| 8420 | Brain (AI server) | Мозг |
| 8421 | Desktop control | Управление компьютером |
| 8754 | Main API, chat | Основной API, чат |
| 3000 | Web chat (optional) | Веб-чат (опционально) |

---

## AI Brain / ИИ Мозг

FOL uses AI from the cloud (internet). It does NOT use your computer's memory or battery for AI.

### How to Choose a Brain / Как выбрать мозг

In the file `.env`, set `FOL_BRAIN`:

| `FOL_BRAIN` | What | На русском |
|-------------|------|------------|
| `current` | **Default.** Uses OpenRouter API. Free models available. | По умолчанию. Через API. |
| `freebuff` | Starts Freebuff in background. | Запускает Freebuff в фоне |
<<<<<<< HEAD
=======
| `codebuff` | Paid. Needs `CODEBUFF_API_KEY`. | Платный |
>>>>>>> f6e354dd7c7bbb2971157a338730d3911762af80

### Free AI Models / Бесплатные модели

Set this in `.env`:
```
LLM_MODEL=openrouter/deepseek/deepseek-v4-flash
```
This is **free**! Get a key at [openrouter.ai](https://openrouter.ai) — 2 minutes.

### Backup Models / Запасные модели

If the main model is down, FOL tries backup models:
```
LLM_FALLBACK_MODELS=openrouter/moonshotai/mimo-2.5,openrouter/nvidia/nemotron-3-super-120b-a12b:free
```

---

## Install / Установка

### What You Need / Что нужно

- Mac with Apple Silicon (M1, M2, M3, or M4)
- macOS 14+
- Python 3.10+ (`brew install python@3.10`)
- Node.js (optional, for web chat)

### Step 1: Get the Code / Скачать код

```bash
git clone https://github.com/abdulakimabdimanapov-rgb/SecondSelf.git SecondSelf
cd SecondSelf
```

### Step 2: Make Config File / Создать конфиг

```bash
cp .env.template .env
```

Open `.env` in any text editor (TextEdit, VS Code, Nano). Add your API key:

```env
# Free (use this!):
LLM_MODEL=openrouter/deepseek/deepseek-v4-flash
OPENROUTER_API_KEY=your-key-here

# Or paid:
# LLM_MODEL=openai/gpt-4o-mini
```

Get a free key: [openrouter.ai](https://openrouter.ai) (2 minutes).

### Step 3: Install Packages / Установить пакеты

```bash
pip install -r requirements.txt
```

### Step 4: Start FOL / Запустить FOL

```bash
./run_all.sh
```

**Done!** FOL is running. Open http://localhost:8754 in your browser.

### Step 5 (Optional): Mac App / Приложение

```bash
cd fol-app
swift build
swift run
```

This makes a small app in your MacBook's notch.

---

## Config File / Файл настроек

All settings are in `.env`. Copy from `.env.template` first.

### Main Settings / Основные настройки

| Setting | What | Default | На русском |
|---------|------|---------|------------|
| `LLM_MODEL` | AI model | `openrouter/deepseek/deepseek-v4-flash` | Модель ИИ |
| `OPENROUTER_API_KEY` | Your key | — | Ваш ключ |
| `LLM_MAX_TOKENS` | Answer length | `1500` | Длина ответа |
| `LLM_TEMPERATURE` | Creativity | `0` | Креативность |
| `FOL_BRAIN` | Brain mode | `current` | Режим мозга |

### Many Keys / Много ключей

If you have many OpenRouter keys, FOL uses them one by one:

```env
OPENROUTER_API_KEY=sk-first-key
OPENROUTER_API_KEY_2=sk-second-key
OPENROUTER_API_KEY_3=sk-third-key
# ... up to 99!
```

When one key is limited (error 429), FOL automatically uses the next key.

### Memory / Память

| Setting | What | На русском |
|---------|------|------------|
| `OBSIDIAN_API_KEY` | Obsidian API key | Ключ Obsidian |
| `OBSIDIAN_VAULT_PATH` | Obsidian folder | Папка Obsidian |
| `TAVILY_API_KEY` | Web search (optional) | Поиск в интернете |

---

## How to Use / Как пользоваться

### Start / Запуск

```bash
./run_all.sh          # all services / все сервисы
./run_all.sh status   # check status / проверить статус
./run_all.sh stop     # stop / остановить
```

### Chat / Чат

Open in browser: http://localhost:8754

Or use terminal:
```bash
curl -X POST http://localhost:8754/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'
```

### Voice / Голос

1. Open app: `cd fol-app && swift run`
2. Click microphone in the notch
3. Speak!

---

## Project Files / Файлы проекта

```
SecondSelf/
├── fol/                # Python AI core (main code)
│   ├── core/           #   App controller
│   ├── modules/        #   All modules (LLM, tools, memory, voice)
│   ├── tests/          #   1073+ tests
│   └── docs/           #   Documentation
├── orchestrator/       # AI server (:8420)
│   ├── server.py       #   Main server
│   └── agents/         #   5 agents (Architect, Coder, etc.)
├── agent-server/       # Desktop control (:8421)
├── fol-app/            # Swift notch app
├── tests/              # More tests
├── analyze/            # Analysis
├── obsidian/           # Obsidian memory
├── src/                # Web chat (Next.js)
├── run_all.sh          # Start script
├── requirements.txt    # Python packages
└── .env.template       # Config template
```

---

## Safety / Безопасность

FOL has safety rules. **Dangerous actions need your permission.**

| Risk Level | What | Permission | На русском |
|------------|------|-----------|------------|
| 1 — Safe | Read screen, search | No | Безопасно |
| 2 — Navigation | Open app, focus window | No | Навигация |
| 3 — GUI | Click, type, hotkeys | Light warning | Управление |
| 4 — Files | Write file, send email | **Must approve** | Файлы |
| 5 — Danger | Shell commands, delete | **Must approve** | Опасно |

The AI **cannot** approve its own actions. Only you can.

---

## Tests / Тесты

```bash
# All tests / Все тесты
python3 -m pytest tests/ -v

# FOL tests (1073+) / Тесты FOL
python3 -m pytest fol/tests/ -v

# Russian tests / Русские тесты
python3 -m pytest tests/test_router.py -v -k "russian"

# Bilingual tests / Двуязычные тесты
python3 -m pytest tests/test_router.py -v -k "bilingual"

# Build Swift app / Собрать приложение
cd fol-app && swift build
```

---

## Roadmap / Планы

### Done / Готово ✅

- Notch panel with 4 states
- Chat with AI (real time answers)
- 50+ tools (apps, browser, files)
- Russian + English (with typo fix)
- Free AI models (OpenRouter)
- Backup models (auto switch)
- Many API keys (auto rotation)
- Obsidian memory (6 layers)
- Smart suggestions
- Screen detection
- Safety (dangerous actions need approval)
- Voice input (offline, no API key)
- 1073+ tests passing

### In Progress / В работе 🚧

- Freebuff auto-start
- Better screen understanding
- Memory 2.0 (facts, preferences, projects)

### Planned / Планы 📋

- Cloud sync (same memory on all devices)
- Knowledge graph (smart connections)
- Plugin system (other devs can add features)
- Visual workflow builder
- iOS app
- Text-to-speech (FOL talks back)
- Personal dashboard

---

## Problems? / Проблемы?

| Problem | Solution | Решение |
|---------|----------|---------|
| "Port already in use" | `lsof -ti :8420 \| xargs kill` | Убить процесс |
| "Python not found" | `brew install python@3.10` | Установить Python |
| "API key error" | Add key to `.env` | Добавить ключ в `.env` |
| "mlx-whisper not installed" | `pip install mlx-whisper` | Установить для голоса |

---

## Contributing / Вклад

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug fixes and feedback welcome!

---

## License

MIT — see [LICENSE](LICENSE).

---

*FOL — Future of Life. Your smart helper that never sleeps.*

*FOL — Будущее Жизни. Умный помощник, который никогда не спит.*
