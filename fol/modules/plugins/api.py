"""Plugin API — REST API endpoints for plugin management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PluginInfo:
    """Plugin information for API responses."""

    name: str
    version: str
    description: str
    enabled: bool
    author: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "enabled": self.enabled,
            "author": self.author,
        }


def get_plugin_api_docs() -> str:
    """Return API documentation for plugins."""
    return """
# FOL Plugin API

## Endpoints

### GET /plugins
List all registered plugins.

### POST /plugins/{name}/enable
Enable a plugin.

### POST /plugins/{name}/disable
Disable a plugin.

### GET /plugins/{name}
Get plugin details.

## Creating a Plugin

1. Create a directory in `plugins/` with your plugin name
2. Add `manifest.json`:
```json
{
    "name": "my-plugin",
    "version": "0.1.0",
    "description": "My FOL plugin",
    "author": "Your Name"
}
```
3. Add `plugin.py` with a class extending `FOLPlugin`:
```python
from modules.plugins.base import FOLPlugin

class MyPlugin(FOLPlugin):
    name = "my-plugin"
    version = "0.1.0"

    async def on_load(self):
        print("Plugin loaded!")

    async def on_event(self, event):
        print(f"Event: {event.type}")
```

## Hooks

- `on_load()` / `on_unload()` — lifecycle
- `on_enable()` / `on_disable()` — enable/disable
- `on_event(event)` — all events
- `on_user_input(text) -> str | None` — modify input before LLM
- `before_llm_call(messages) -> messages` — modify messages before LLM
- `after_llm_response(response) -> str` — modify LLM response
"""
