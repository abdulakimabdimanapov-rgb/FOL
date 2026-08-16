# F.O.L. — Friendly Obedient Listener

> Personal AI Assistant with JARVIS-level capabilities, running locally on MacBook Air M2.

## Quick Start

```bash
# Setup (one time)
cd Desktop/FOL/fol
source .venv/bin/activate

# Run interactive mode
PYTHONPATH=. python -m core.app start --interactive

# Send a single command
PYTHONPATH=. python -m core.app send "hello"
```

## Features

### Voice (TTS/STT)
- macOS text-to-speech via `say` command
- Speech-to-text via `speech_recognition` + `sounddevice`
- Wake word detection ("Hey FOL")
- Bilingual commands (English + Russian)

### Vision
- Screenshot capture
- Active window detection
- Running apps list
- OCR text extraction (macOS Vision framework)

### Intelligence
- Local LLM inference via MLX (Apple Silicon)
- Cloud backends: OpenAI, Anthropic, Gemini
- Automatic failover between backends
- ReAct agent for multi-step reasoning
- Function calling (tool use)

### Memory
- Short-term: conversation history, working memory
- Long-term: knowledge triples, episodic memory, vector search
- Preference storage and learning
- Entity/fact extraction from conversations

### Tools (16 built-in)
- `execute_command` — Run shell commands
- `open_app` — Open macOS applications
- `search_files` / `read_file` / `write_file` — File operations
- `move_mouse` / `click` / `drag` — Mouse control
- `type_text` / `press_key` — Keyboard control
- `browser_navigate` / `browser_search` — Web browsing
- `clipboard` — Read/write clipboard
- `system_info` — System information

### REST API + WebSocket
- `GET /health` — Health check
- `POST /conversation/send` — Chat
- `GET /tools/` — List tools
- `POST /tools/{name}/execute` — Execute tool
- `WS /ws` — Real-time communication

### Plugin System
- Load/unload plugins at runtime
- Event hooks (on_input, before_llm, after_llm)
- Custom tools via plugins

## Commands

| Command | Description |
|---------|-------------|
| `hello` / `hi` | Greet FOL |
| `help` | Show all commands |
| `status` | System status |
| `time` / `date` | Current time/date |
| `remember <text>` | Store a memory |
| `recall` | Show memories |
| `voice on/off` | Toggle voice output |
| `screenshot` | Take screenshot |
| `what's on screen` | Analyze screen |
| `active window` | Get active window |
| `read screen` | OCR text from screen |
| `memory` | Long-term memory status |
| `search memory <query>` | Search memories |
| `learn <text>` | Store permanently |
| `what do you know` | Show knowledge |
| `run <cmd>` | Execute command |
| `open <app>` | Open application |
| `shutdown` | Exit FOL |

## Configuration

Edit `.env`:

```bash
# LLM backend (mlx | openai | anthropic | gemini)
FOL_LLM_BACKEND=mlx
FOL_LLM_MODEL=mlx-community/Qwen2.5-0.5B-Instruct-4bit

# Cloud API (optional)
FOL_OPENAI_API_KEY=sk-...

# Speech
FOL_STT_LANGUAGE=en-US
```

## Development

```bash
# Run tests
source .venv/bin/activate
PYTHONPATH=. python -m pytest tests/ -v

# Debug mode
PYTHONPATH=. python -m core.app start --debug
```

## Tech Stack

- **Python 3.12+** — Core language
- **MLX** — Apple Silicon local inference
- **ChromaDB** — Vector store
- **FastAPI** — REST API
- **Pydantic** — Settings & validation
- **Structlog** — Structured logging

## License

MIT
