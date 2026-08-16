# Plugin System

## Overview

FOL's plugin system allows extending functionality without modifying core code.

## Creating a Plugin

### 1. Create Plugin Directory

```
plugins/my_plugin/
├── __init__.py
├── plugin.py
└── manifest.json
```

### 2. Plugin Class

```python
# plugins/my_plugin/plugin.py
from modules.plugins.base import FOLPlugin

class MyPlugin(FOLPlugin):
    name = "my-plugin"
    version = "0.1.0"
    description = "My awesome plugin"

    async def on_load(self):
        """Called when plugin is loaded."""
        pass

    async def on_unload(self):
        """Called when plugin is unloaded."""
        pass

    async def on_event(self, event):
        """Handle system events."""
        pass

    async def on_user_input(self, text: str) -> str | None:
        """Intercept user input. Return None to let FOL handle it."""
        if "weather" in text.lower():
            return "It's sunny today! ☀️"
        return None
```

### 3. Manifest

```json
{
  "name": "my-plugin",
  "version": "0.1.0",
  "description": "My awesome plugin",
  "author": "Your Name",
  "entry_point": "plugin:MyPlugin"
}
```

## Plugin Hooks

| Hook | When | Use Case |
|------|------|----------|
| `on_load` | Plugin loaded | Initialize resources |
| `on_unload` | Plugin unloaded | Cleanup |
| `on_enable` | Plugin enabled | Start functionality |
| `on_disable` | Plugin disabled | Pause functionality |
| `on_event` | Any system event | React to events |
| `on_user_input` | User input received | Intercept/filter input |
| `before_llm_call` | Before LLM call | Modify context |
| `after_llm_response` | After LLM response | Post-process output |
| `on_tool_execute` | Before tool execution | Modify/intercept tools |
| `on_memory_retrieve` | Memory retrieval | Augment results |
| `on_memory_store` | Memory storage | Filter/modify storage |
| `on_error` | Any error | Error handling |

## Managing Plugins

```bash
# List plugins
curl http://localhost:8754/plugins/

# Enable plugin
curl -X POST http://localhost:8754/plugins/my-plugin/enable

# Disable plugin
curl -X POST http://localhost:8754/plugins/my-plugin/disable
```

## API for Plugin Developers

```python
from modules.plugins.base import FOLPlugin
from modules.tools.base import AbstractTool, ToolResult

class WeatherPlugin(FOLPlugin):
    name = "weather"
    version = "0.1.0"

    # Custom tools provided by plugin
    tools = [WeatherTool()]

class WeatherTool(AbstractTool):
    name = "get_weather"
    description = "Get weather for a location"
    parameters = {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name"}
        },
        "required": ["location"]
    }

    async def execute(self, params: dict) -> ToolResult:
        # Implement weather API call
        return ToolResult(success=True, output="Sunny, 25°C")
```
