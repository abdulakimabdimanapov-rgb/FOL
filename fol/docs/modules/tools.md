# Tools Module

## Overview

The Tools module provides instruments for FOL to interact with the computer.

## Tool Categories

### System Tools

| Tool | Description | Permission |
|------|-------------|------------|
| `execute_command` | Run terminal commands | HIGH |
| `open_app` | Open applications | MEDIUM |
| `search_files` | Find files by name/content | MEDIUM |
| `read_file` / `write_file` | File operations | MEDIUM |
| `system_info` | CPU, RAM, disk info | LOW |

### Mouse/Keyboard Tools

| Tool | Description | Permission |
|------|-------------|------------|
| `move_mouse` | Move cursor to coordinates | HIGH |
| `click` | Click at coordinates | HIGH |
| `drag` | Drag from point A to B | HIGH |
| `type_text` | Type text string | HIGH |
| `press_key` | Press keyboard key/shortcut | HIGH |

### Browser Tools

| Tool | Description | Permission |
|------|-------------|------------|
| `browser_navigate` | Open URL in browser | MEDIUM |
| `browser_search` | Search the web | MEDIUM |
| `get_page_content` | Extract page text | MEDIUM |
| `web_scraper` | Scrape page content | MEDIUM |
| `bookmarks` | Manage bookmarks | LOW |

### Automation Tools

| Tool | Description | Permission |
|------|-------------|------------|
| `run_workflow` | Execute step sequences | HIGH |
| `schedule` | Schedule periodic tasks | MEDIUM |
| `recorder` | Record/replay actions | HIGH |

### Other Tools

| Tool | Description | Permission |
|------|-------------|------------|
| `read_clipboard` | Read clipboard content | MEDIUM |
| `write_clipboard` | Write to clipboard | MEDIUM |

## API

### ToolRegistry

```python
from modules.tools.registry import ToolRegistry

registry = ToolRegistry()
registry.register(ExecuteCommand())
result = await registry.execute("execute_command", {"command": "ls"})
print(result.output)
```

### Custom Tool

```python
from modules.tools.base import AbstractTool, ToolResult

class MyTool(AbstractTool):
    name = "my_tool"
    description = "Does something useful"
    parameters = {
        "type": "object",
        "properties": {"input": {"type": "string"}},
        "required": ["input"],
    }

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, output=f"Processed: {params['input']}")
```
