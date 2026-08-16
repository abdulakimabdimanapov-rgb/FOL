# FOL Developer Guide

## Project Structure

```
fol/
├── config/          # Settings, constants, logging
├── core/            # Event bus, orchestrator, lifecycle, health, security, performance
├── modules/
│   ├── input/       # Text, speech, screen, vision
│   ├── llm/         # LLM engine, backends, agent, router, learner, proactive
│   ├── memory/      # Vector store, conversation, KG, preferences, RAG
│   ├── tools/       # System, mouse/keyboard, browser, clipboard
│   ├── output/      # TTS, display, notifications
│   └── plugins/     # Plugin loader, manager, hooks, API
├── tests/           # Unit and integration tests
├── plugins/         # User plugins directory
└── docs/            # Documentation
```

## Adding a New Tool

1. Create `modules/tools/my_tool.py`:

```python
from modules.tools.base import AbstractTool, ToolResult, Permission

class MyTool(AbstractTool):
    name = "my_tool"
    description = "Does something useful"
    parameters = {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Input text"},
        },
        "required": ["input"],
    }
    required_permissions = [Permission.MEDIUM]

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, output="Done!")
```

2. Register in `core/app.py`:

```python
from modules.tools.my_tool import MyTool
self._tools.register(MyTool())
```

3. Add tests in `tests/modules/tools/test_my_tool.py`.

## Adding a New LLM Backend

1. Create `modules/llm/backends/my_backend.py`:

```python
from modules.llm.base import AbstractLLMBackend, LLMResponse

class MyBackend(AbstractLLMBackend):
    name = "my_backend"

    async def initialize(self):
        # Load model or connect to API
        pass

    async def shutdown(self):
        pass

    async def generate(self, messages, *, max_tokens=4096, temperature=0.7):
        return LLMResponse(text="response", model="my_model")
```

2. Register in `modules/llm/engine.py`.

## Writing a Plugin

See `plugins/example_plugin/` for a complete example.

Key points:
- Extend `FOLPlugin` base class
- Implement `on_load()` and `on_unload()`
- Override hooks as needed
- Add `manifest.json` with metadata

## Running Tests

```bash
PYTHONPATH=. python3 -m pytest tests/ -v
PYTHONPATH=. python3 -m pytest tests/ -v -k "test_name"
PYTHONPATH=. python3 -m pytest tests/core/ -v
```

## Code Style

- Type hints everywhere
- Async/await for I/O operations
- Structured logging (structlog)
- Pydantic for data validation
- Max 100 chars per line
