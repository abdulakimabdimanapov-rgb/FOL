# F.O.L. User Guide

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd FOL/fol

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your settings
```

## Quick Start

```bash
# Start interactive mode
PYTHONPATH=. python3 -m core.app start --interactive

# Send a single command
PYTHONPATH=. python3 -m core.app send "hello"

# Start with debug logging
PYTHONPATH=. python3 -m core.app start --debug
```

## Commands

| Command | Description |
|---------|-------------|
| `hello` / `hi` | Greet FOL |
| `help` | Show available commands |
| `time` | Current time |
| `date` | Today's date |
| `status` | System status |
| `remember <text>` | Save a note |
| `notes` | Show saved notes |
| `open <App>` | Open an application |
| `run <cmd>` | Execute a shell command |
| `scan screen` | Take a screenshot |
| `screen status` | Describe what's on screen |

## Configuration

Edit `.env` to configure FOL:

```bash
# LLM backend (mlx | openai | anthropic | gemini)
FOL_LLM_BACKEND=mlx
FOL_LLM_MODEL=mlx-community/Llama-3.2-3B-Instruct-4bit

# Cloud API (optional)
FOL_OPENAI_API_KEY=sk-...

# Speech recognition
FOL_STT_MODEL=medium
FOL_STT_LANGUAGE=ru

# Memory
FOL_MEMORY_MAX_RESULTS=10
```

## Voice Mode

FOL supports voice input/output:

- **Push to Talk**: Hold the configured hotkey to speak
- **Always-on**: Continuously listens for wake word
- **Text mode**: Type commands directly in the interactive shell

## Plugin System

FOL supports plugins for extending functionality. See [Developer Guide](developer_guide.md) for details.

## Troubleshooting

### FOL won't start
- Check Python version: `python3 --version` (requires 3.12+)
- Check dependencies: `pip install -e ".[dev]"`
- Check logs: `tail -f ~/.fol/logs/fol.log`

### LLM not responding
- Verify backend configuration in `.env`
- For local models: ensure MLX is installed
- For cloud APIs: verify API key is set

### Voice not working
- Check microphone permissions in System Preferences
- Ensure `mlx-whisper` is installed
- Try a smaller model: `FOL_STT_MODEL=tiny`
