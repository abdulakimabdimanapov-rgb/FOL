"""Obsidian bridge configuration.

Читает настройки из .env с fallback на значения по умолчанию.
"""

from __future__ import annotations

import os
from pathlib import Path

# Load .env BEFORE reading env vars. The orchestrator imports obsidian.*
# modules before it calls load_dotenv() itself, so without this the API key
# would always be empty here and Obsidian memory would be silently disabled.
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass  # dotenv optional — env vars may be set by the shell instead


# Obsidian Local REST API plugin
# Устанавливается в Settings → Community Plugins → Local REST API
OBSIDIAN_API_URL = os.environ.get(
    "OBSIDIAN_API_URL",
    "https://127.0.0.1:27124",
)
OBSIDIAN_API_KEY = os.environ.get("OBSIDIAN_API_KEY", "")

# Путь к Obsidian vault на диске (для init_vault)
VAULT_PATH = Path(
    os.environ.get(
        "OBSIDIAN_VAULT_PATH",
        str(Path.home() / "Obsidian" / "FOL"),
    )
)

# API endpoints (v5 contract — the client builds URLs directly)
# Observed live against plugin 5.0.2:
#   GET  /                      → {"status": "OK"}
#   PUT  /vault/{path}          → body {"content": ..., "type": "file"} → 204
#   GET  /vault/{path}          → {"content": ..., "type": "file"}
#   GET  /vault/{dir}/          → {"files": [...]}
#   POST /search/simple/?query= → [ {filename, score, matches: [...]} ]
#   PATCH /vault/{path}         → body InstructionInput (markdown-patch 2.0)

# SSL verification (self-signed cert)
VERIFY_SSL = False

# Default tags для новых заметок
DEFAULT_TAGS = ["fol", "auto-generated"]

# Структура vault (папки для init_vault)
VAULT_STRUCTURE = [
    "Profile",
    "Projects",
    "Knowledge",
    "Goals",
    "Ideas",
    "Tasks",
    "Decisions",
    "Conversations",
    "Daily",
    "Episodic",
    "Templates",
    "Archive",
]

# Папки с автогенерируемым _index.md (по умолчанию — все основные)
INDEX_FOLDERS = [
    "Profile",
    "Projects",
    "Knowledge",
    "Goals",
    "Ideas",
    "Tasks",
    "Decisions",
    "Conversations",
    "Daily",
    "Episodic",
]

# Шаблоны заметок: имя файла → содержимое (создаются в Templates/)
TEMPLATES: dict[str, str] = {
    "project.md": """---
type: project
status: in-progress
created: {{date}}
---

# {{title}}

## Цель

## Задачи
- [ ] 

## Заметки

## Links
- 
""",
    "idea.md": """---
type: idea
status: idea
created: {{date}}
---

# {{title}}

## Описание

## Почему это круто

## Links
- 
""",
    "decision.md": """---
type: decision
status: accepted
created: {{date}}
---

# {{title}}

## Контекст

## Решение

## Альтернативы
- 

## Links
- 
""",
    "knowledge.md": """---
type: knowledge
created: {{date}}
tags: []
---

# {{title}}

## Суть

## Детали

## Links
- 
""",
    "daily.md": """---
type: daily
created: {{date}}
---

# {{date}}

## 🎯 Focus
- 

## ✅ Done
- 

## 📝 Notes
- 

## 🔗 Links
- 
""",
}


def is_configured() -> bool:
    """Check if Obsidian API key is set."""
    return bool(OBSIDIAN_API_KEY) and OBSIDIAN_API_KEY != "your-api-key-here"
