# FOL + SecondSelf — Объединённый проект

> Дата слияния: 29 июля 2026
> Команда: Buffy (AI-агент Freebuff)
> 
> **Задача:** Объединить два проекта (FOL и SecondSelf) в одну программу,
> удалить лишние файлы, создать единую структуру.

---

## 1. Что было сделано

### Задача от пользователя
Пользователь попросил:
1. Объединить два проекта — **FOL** и **SecondSelf**
2. Сделать одно целое (единая программа)
3. Удалить лишние файлы
4. Протестировать результат
5. Создать этот файл документации, чтобы новая модель AI сразу поняла суть проекта

### Выполненные шаги

| Шаг | Действие | Команда/Инструмент |
|-----|----------|-------------------|
| 1 | Изучение структуры обоих проектов | `read_files`, `read_subtree` |
| 2 | Выяснение что FOL — более старая версия SecondSelf | Анализ `FOL/fol/ui/macos/Sources/SecondSelf/*` — код ВНУТРИ FOL уже назывался SecondSelf |
| 3 | Создание `MERGED_README.md` (этот файл) | `write_file` |
| 4 | Копирование Python-бэкенда FOL в SecondSelf/fol/ | `cp -r FOL/fol SecondSelf/fol` |
| 5 | Обновление `requirements.txt` (добавлены зависимости FOL) | `str_replace` |
| 6 | Обновление `.gitignore` | `str_replace` |
| 7 | Создание унифицированного запускающего скрипта `run_all.sh` | `write_file` |
| 8 | Удаление дублирующихся корневых файлов | `rm` |
| 9 | Удаление папки FOL (код перемещён в SecondSelf/fol/) | `rm -rf FOL` |
| 10 | Проверка сборки Swift приложения | `swift build` |
| 11 | Проверка Python импортов | `python -c "import ..."` |

---

## 2. Структура объединённого проекта

```
<project-root>/
├── MERGED_README.md           ← ВЫ ЗДЕСЬ (документация о слиянии)
├── FOL_UPGRADE.md              # Оригинальный мастер-документ архитектуры
├── README.md                   # Основное README
├── CLAUDE.md                   # Контекст для AI-модели
├── DESIGN.md                   # Дизайн-система
│
├── fol/                        # ← ПЕРЕМЕЩЕНО из FOL/fol/
│   ├── core/                   # Ядро FOL (app, orchestrator, lifecycle, event_bus)
│   ├── modules/                # Модули FOL (LLM, tools, memory, input, output)
│   │   ├── llm/                #   LLM engine (MLX, OpenAI, Anthropic, Gemini)
│   │   ├── tools/              #   Tool system (browser, mouse/keyboard, system)
│   │   ├── memory/             #   Memory system (RAG, vector store, knowledge graph)
│   │   ├── input/              #   Input modules (speech, vision, text, screen)
│   │   ├── output/             #   Output modules (TTS, display, notifications)
│   │   └── plugins/            #   Plugin system
│   ├── config/                 # Настройки FOL (settings, constants, logging)
│   ├── api/                    # REST + WebSocket API сервер
│   │   ├── rest/               #   REST API routes
│   │   └── websocket/          #   WebSocket handler
│   ├── plugins/                # Plugin examples
│   ├── ui/web/                 # Web UI (HTML)
│   ├── tests/                  # Тесты FOL
│   ├── docs/                   # Документация FOL
│   ├── scripts/                # Скрипты FOL
│   ├── main.py                 # Entry point FOL
│   ├── run_api_server.py       # Запуск REST API сервера на порту 8754
│   └── fol_mac_app.py          # PyObjC macOS приложение FOL
│
├── SecondSelf/                 # SwiftUI macOS приложение (НЕ ТРОНУТО)
│   ├── SecondSelfApp.swift     # Entry point
│   ├── NotchPanel.swift        # NSPanel notch UI
│   ├── ViewModels/             # ChatViewModel, etc.
│   ├── Views/                  # Все SwiftUI вьюхи
│   ├── Models/                 # ChatMessage, A2UI, SSE, TwinState
│   ├── Services/               # Audio, ElevenLabs, Speech
│   └── Utilities/              # DesignTokens, AudioManager
│
├── orchestrator/               # FastAPI сервер (порт 8420)
├── agent-server/               # Python HTTP сервер (порт 8421)
├── src/                        # Next.js web frontend + FastAPI backend
├── auth/                       # Python auth модули
├── fetch/                      # Python fetch модули (Gmail, Tavily, Calendar)
├── analyze/                    # Анализ (voice, behavior, topics, relationships)
├── clean/                      # Email cleaning
├── utils/                      # Utilities (episodic_writer, daily_tracker)
├── context_engine/             # Контекст экрана (app_monitor, browser_url)
├── obsidian/                   # Obsidian bridge (L5 память)
├── dashboard/                  # Web dashboard
├── cookie_sync/                # Cookie syncing
├── bridge/                     # Phone bridge
├── setup/                      # LaunchAgent setup scripts
├── tests/                      # Python тесты (1168+810)
│
├── main.py                     # Identity pipeline CLI
├── requirements.txt            # Объединённые Python зависимости
├── run_all.sh                  # ← НОВЫЙ: единый запуск всех сервисов
├── package.json                # Next.js зависимости
└── tsconfig.json               # TypeScript конфиг
```

---

## 3. Порты и сервисы

| Порт | Сервис | Откуда | Описание |
|------|--------|--------|----------|
| 8420 | Orchestrator | SecondSelf (FastAPI) | Главный AI-сервер, LLM агент |
| 8421 | Agent Server | SecondSelf | Десктоп/браузер контроль |
| 8754 | FOL API | FOL (FastAPI) | JARVIS-команды, REST API |
| 3000 | Next.js | SecondSelf | Web интерфейс |
| 5901 | VNC (резерв) | secondself | VNC доступ |
| 9222 | Chrome CDP | secondself | Chrome DevTools |

---

## 4. Как запускать

### Быстрый запуск всех сервисов
```bash
cd ~/Desktop/SecondSelf
./run_all.sh
```

### Запуск отдельных компонентов
```bash
# macOS SwiftUI приложение
cd ~/Desktop/SecondSelf/SecondSelf && swift run

# Orchestrator (порт 8420)
cd ~/Desktop/SecondSelf && python orchestrator/server.py

# Agent Server (порт 8421)
cd ~/Desktop/SecondSelf && python agent-server/server.py

# FOL API сервер (порт 8754)
cd ~/Desktop/SecondSelf && python fol/run_api_server.py

# Identity Pipeline
cd ~/Desktop/SecondSelf && python main.py

# Next.js Web Frontend
cd ~/Desktop/SecondSelf && npm run dev
```

### Запуск тестов
```bash
# Python тесты
cd ~/Desktop/SecondSelf && python -m pytest tests/ -v

# Swift сборка
cd ~/Desktop/SecondSelf/SecondSelf && swift build

# FOL тесты
cd ~/Desktop/SecondSelf && python -m pytest fol/tests/ -v
```

---

## 5. Отношение между FOL и SecondSelf

### FOL (старая версия)
FOL (`/FOL/`) — это **первая версия** AI-ассистента, написанная на Python с:
- Полноценным JARVIS-подобным AI ассистентом
- Голосовым управлением (STT/TTS)
- Системой видения (screenshot, OCR, active window)
- Модульной системой инструментов (браузер, мышь/клавиатура, система)
- LLM с несколькими бэкендами (MLX локально, OpenAI, Anthropic, Gemini)
- REST + WebSocket API
- Старой версией Swift macOS приложения (уже называлась "SecondSelf")

### SecondSelf (новая версия)
SecondSelf (`/SecondSelf/`) — это **эволюционировавшая версия** с:
- Улучшенным SwiftUI macOS приложением с продвинутыми анимациями
- Архитектурой на основе AI-агентов (orchestrator)
- Web-фронтендом (Next.js)
- Identity Pipeline (Gmail, Tavily, Calendar анализ)
- Живой памятью через Obsidian
- Контекстным движком (мониторинг экрана)
- Системой проактивных предложений

### Что дало слияние
- **SecondSelf** предоставляет: красивый Notch UI, агентную архитектуру, веб-интерфейс, живую память
- **FOL** предоставляет: JARVIS-команды, локальный LLM (MLX), расширенную систему инструментов, плагины
- Вместе: полноценный AI-ассистент нового поколения

---

## 6. Ключевые решения при слиянии

| Решение | Причина |
|---------|---------|
| SecondSelf — основной проект | Новая версия, лучше архитектура, SwiftUI |
| FOL → SecondSelf/fol/ | Сохраняем весь код FOL как подмодуль |
| Swift код FOL удалён | Устарел, заменён SecondSelf Swift кодом |
| build артефакты FOL удалены | Не нужны, пересобираются из исходников |
| MASTER_PROMPT_* файлы удалены | Заменены FOL_UPGRADE.md и MERGED_README.md |
| `run_all.sh` создан | Единый запуск всех сервисов |

---

## 7. Для новой AI-модели

Когда новая модель заходит в этот проект:

1. **Прочитай `MERGED_README.md`** — ты уже здесь ✓
2. **Прочитай `FOL_UPGRADE.md`** — мастер-документ архитектуры
3. **Прочитай `CLAUDE.md`** — контекст Identity Pipeline
4. **Прочитай `DESIGN.md`** — дизайн-система
5. **Прочитай `orchestrator/server.py`** — главный AI сервер
6. **Посмотри `SecondSelf/`** — SwiftUI UI слой

### Ключевые принципы:
- **FOL** предоставляет Python AI-ядро (JARVIS-команды, MLX, инструменты)
- **SecondSelf** предоставляет UI и агентную архитектуру
- **Не переписывай работающий код** — только рефактори или добавляй новое
- **Type hints** — обязательны везде
- **Модульность** — каждый модуль независим и тестируем
- **Сначала архитектура → потом код**

### Важные порты:
- `localhost:8420` — Orchestrator (главный AI)
- `localhost:8421` — Agent Server (десктоп контроль)
- `localhost:8754` — FOL API (JARVIS-команды)
- `localhost:3000` — Next.js web

---

*FOL + SecondSelf = Единый AI-ассистент нового поколения*
*Личный цифровой двойник на MacBook*
