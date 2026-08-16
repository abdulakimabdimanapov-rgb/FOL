# Obsidian Memory Integration — Layer 5 Semantic Memory

> **Статус:** Спецификация (Phase 6 из FOL_UPGRADE.md)
> **Цель:** Obsidian vault как долговременная семантическая память FOL
> **Архитектура:** Obsidian Local REST API Plugin (Python bridge)

---

## 1. ЗАЧЕМ

Текущая система памяти FOL (Layers 1-4) использует плоские `.md` файлы в `~/.secondself/`:
- `identity.md` — кто ты
- `preferences.md` — как ты работаешь  
- `episodic.md` — что произошло

**Проблемы текущей системы:**
- Нет связей между заметками (все изолированы)
- Нет поиска по содержимому
- Нет визуальной навигации
- Нет структуры проектов и знаний
- Нет истории изменений (git/vault history)

**Что даёт Obsidian:**
- Визуальный граф связей (`[[wikilinks]]`)
- Мощный полнотекстовый поиск
- Graph View для навигации
- Git-совместимый Markdown
- Плагины (Kanban, Calendar, Excalidraw)
- Мобильная синхронизация (iCloud / Obsidian Sync)

---

## 2. АРХИТЕКТУРА

```
┌──────────────────────────────────────────────────────────┐
│                    FOL Orchestrator :8420                 │
│                                                          │
│  ┌─────────────────────────────────────────────────┐     │
│  │              obsidian_bridge.py                  │     │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────────┐   │     │
│  │  │ Vault    │ │ Search   │ │ Semantic      │   │     │
│  │  │ Read/Write│ │ Engine  │ │ Linking Engine│   │     │
│  │  └────┬─────┘ └────┬─────┘ └──────┬────────┘   │     │
│  └───────┼────────────┼──────────────┼─────────────┘     │
│          │            │              │                    │
│          ▼            ▼              ▼                    │
│  ┌─────────────────────────────────────────────────┐     │
│  │         REST API (HTTPS localhost:27124)         │     │
│  │         Authorization: Bearer <api-key>          │     │
│  └─────────────────────┬───────────────────────────┘     │
└────────────────────────┼─────────────────────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │    Obsidian App      │
              │  (Local REST Plugin) │
              └──────────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │   ~/Obsidian/FOL/    │
              │   (Vault Directory)  │
              │                      │
              │  Profile/           │
              │  Projects/          │
              │  Knowledge/         │
              │  Goals/             │
              │  Ideas/             │
              │  Tasks/             │
              │  Decisions/         │
              │  Conversations/     │
              │  Daily/             │
              │  Archive/           │
              └──────────────────────┘
```

### 2.1 Компоненты

| Компонент | Файл | Роль |
|-----------|------|------|
| Bridge Client | `obsidian/bridge.py` | HTTP клиент к Local REST API |
| Vault Manager | `obsidian/vault.py` | Структура папок, CRUD заметок |
| Search Engine | `obsidian/search.py` | Полнотекстовый поиск по vault |
| Semantic Linker | `obsidian/linker.py` | LLM-генерация связей между заметками |
| Memory Sync | `obsidian/sync.py` | Sync `~/.secondself/` ↔ Obsidian vault |
| Tool Definitions | `obsidian/tools.py` | Инструменты для LLM (Anthropic format) |
| Config | `obsidian/config.py` | Путь к vault, API ключ, настройки |

### 2.2 Поток данных

```
Запрос пользователя
       │
       ▼
LLM решает: нужна память?
       │
       ├── read_note("Projects/Q4-planning")
       │   └── GET /vault/Projects/Q4-planning.md
       │
       ├── search_vault("прошлогодний рефакторинг")
       │   └── POST /search/simple → результаты
       │
       ├── create_note("Ideas/новый-подход-к-архитектуре")
       │   └── PUT /vault/Ideas/....md
       │       └── Semantic Linker: авто-связи с похожими заметками
       │
       ├── append_daily(task, project)
       │   └── PATCH /vault/Daily/2026-04-12.md
       │
       └── log_decision(what, why, alternatives)
           └── PUT /vault/Decisions/....md
               └── Semantic Linker: связи с проектами и идеями
```

---

## 3. СТРУКТУРА VAULT

### 3.1 Директории

```
FOL Vault/
├── .obsidian/                    # Конфигурация Obsidian
│
├── Profile/
│   ├── identity.md               # Sync из ~/.secondself/identity.md
│   ├── preferences.md            # Sync из ~/.secondself/preferences.md
│   └── relationships.md          # Контактный граф
│
├── Projects/
│   ├── _index.md                 # Список всех проектов + статусы
│   ├── Project-Name/
│   │   ├── _index.md             # Обзор проекта
│   │   ├── architecture.md       # Архитектурные решения
│   │   ├── tasks.md              # Todo лист
│   │   ├── notes.md              # Заметки по проекту
│   │   └── retrospective.md      # Что получилось/нет (самоанализ)
│   └── ...
│
├── Knowledge/
│   ├── _index.md                 # Все области знаний
│   ├── programming/              # Папки по категориям
│   ├── design/
│   ├── business/
│   └── ...                       # Автоматически создаются
│
├── Goals/
│   ├── _index.md                 # Все цели
│   ├── quarterly-2026-Q2.md      # Квартальные цели
│   └── roadmap.md                # Долгосрочный roadmap
│
├── Ideas/
│   ├── _index.md                 # Банк идей
│   ├── 2026-04-12-idea-name.md   # Идеи с датой
│   └── ...
│
├── Tasks/
│   ├── _index.md                 # All tasks dashboard
│   ├── active.md                 # Активные задачи
│   ├── backlog.md                # Бэклог
│   └── completed.md              # Выполненные
│
├── Decisions/
│   ├── _index.md                 # Все решения
│   ├── 2026-04-12-decision-name.md
│   └── ...
│
├── Conversations/
│   ├── _index.md                 # Все диалоги
│   ├── 2026-04-12-topic.md       # Важные разговоры с LLM
│   └── ...
│
├── Daily/
│   ├── 2026-04-12.md             # Ежедневные заметки
│   ├── 2026-04-11.md
│   └── ...
│
├── Episodic/
│   ├── _index.md                 # Sync из ~/.secondself/episodic.md
│   └── events.md                 # Все события хронологически
│
└── Archive/                      # Завершённые проекты, старые идеи
    └── ...
```

### 3.2 Формат заметок

**Общий frontmatter (YAML):**
```yaml
---
created: 2026-04-12T14:30:00Z
updated: 2026-04-12T15:45:00Z
tags: [project, architecture, FOL]
aliases: [alt-name]
source: orchestrator
confidence: high
links:
  - "Projects/FOL/architecture.md"
  - "Decisions/2026-04-10-obsidian-layer5.md"
---
```

**Пример заметки:**
```markdown
---
created: 2026-04-12T14:30:00Z
updated: 2026-04-12T15:45:00Z
tags: [project, FOL, memory, obsidian]
source: orchestrator
---

# Obsidian как Layer 5 Semantic Memory

**Связано с:** [[Projects/FOL/architecture]], [[Decisions/2026-04-10-memory-layers]]

## Проблема
Текущая система памяти плоская — нет связей между [[Profile/identity]] 
и [[Projects/...]].

## Решение
Использовать Obsidian vault с автоматическим линкованием через LLM.

## Имплементация
1. `obsidian_bridge.py` — HTTP клиент к Local REST API
2. `semantic_linker.py` — LLM-генерация `[[wikilinks]]`
3. Инструменты для FOL: `read_note`, `write_note`, `search_vault`, `link_notes`

## Статус
🟡 В разработке (Phase 6)

## Ресурсы
- [[Knowledge/obsidian-api]]
- [[Ideas/2026-04-12-auto-linking]]
```

### 3.3 `_index.md` — автоматический индекс

Каждая папка содержит `_index.md` — автоматически сгенерированный список всех заметок в папке с краткими описаниями:

```markdown
# Projects

## Active
- [[Projects/FOL/obsidian-memory]] — Интеграция Obsidian как Layer 5
- [[Projects/FOL/mobile-companion]] — iOS приложение

## Completed
- [[Projects/FOL/identity-pipeline]] — Layer 1 (завершён)

---

*Авто-сгенерировано FOL. Last updated: 2026-04-12*
```

---

## 4. СЕМАНТИЧЕСКИЕ СВЯЗИ

### 4.1 Типы связей

| Тип | Описание | Пример |
|-----|----------|--------|
| `related` | Общая тема | `[[Projects/FOL]]` ↔ `[[Decisions/memory-layers]]` |
| `parent` | Иерархия | `Projects/FOL/` → `Projects/` |
| `depends_on` | Зависимость | `Tasks/auth-refactor` → `Decisions/new-auth` |
| `implements` | Реализация идеи | `Projects/obsidian` → `Ideas/obsidian-memory` |
| `contradicts` | Альтернатива | `Decisions/approach-A` ←→ `Decisions/approach-B` |
| `follow_up` | Продолжение | `Conversations/topic-1` → `Tasks/do-something` |
| `source` | Источник | `Knowledge/obsidian-api` → `url:docs.obsidian.md` |

### 4.2 Semantic Linker Engine

**Алгоритм:**
1. После КАЖДОЙ записи в vault запускается linker
2. Linker берёт текст новой заметки и ищет ПОХОЖИЕ через поиск
3. LLM решает, какие связи создать, и какого они типа
4. Linker добавляет `[[wikilinks]]` в конец заметки под `## Связано с:`
5. Linker также обновляет `links:` в frontmatter

```python
# Псевдокод semantic_liker.py
async def auto_link_note(vault_path: str, content: str):
    # 1. Извлечь ключевые понятия из content
    concepts = await llm_extract_concepts(content)
    # → ["Obsidian", "Layer 5", "semantic memory", "REST API"]
    
    # 2. Поискать похожие заметки по каждому concept
    related = []
    for concept in concepts:
        results = search_vault(concept, limit=3)
        related.extend(results)
    
    # 3. LLM решает, какие связи релевантны
    links = await llm_decide_links(content, related)
    # → [{"target": "Projects/FOL/architecture", "type": "parent"},
    #     {"target": "Knowledge/obsidian-api", "type": "source"}]
    
    # 4. Добавить [[wikilinks]] в заметку
    add_links_to_note(vault_path, links)
    
    # 5. Обновить связанные заметки (backlinks)
    for link in links:
        add_backlink_to_note(link.target, vault_path, link.type)
```

### 4.3 Backlinks (обратные связи)

Когда заметка A ссылается на заметку B, linker автоматически добавляет обратную ссылку в B:

**Заметка A:**
```markdown
## Связано с
- [[Knowledge/obsidian-api]] → источник
```

**Заметка B (`Knowledge/obsidian-api.md`) автоматически обновляется:**
```markdown
## Используется в
- [[Projects/FOL/obsidian-memory]] → реализация
```

---

## 5. OBSIDIAN_BRIDGE — ДЕТАЛЬНАЯ СПЕЦИФИКАЦИЯ

### 5.1 Файловая структура модуля

```
obsidian/
├── __init__.py
├── config.py           # Конфигурация (путь к vault, API key)
├── client.py           # HTTP клиент к Local REST API
├── vault.py            # CRUD операции с заметками
├── search.py           # Поиск по vault
├── linker.py           # Semantic Linker (LLM-связи)
├── sync.py             # Sync ~/.secondself/ ↔ Obsidian
├── tools.py            # FOL Tool definitions
├── daily.py            # Daily note management
└── templates/          # Шаблоны для новых заметок
    ├── project.md
    ├── idea.md
    ├── decision.md
    ├── knowledge.md
    └── daily.md
```

### 5.2 `config.py`

```python
"""Obsidian bridge configuration."""

from pathlib import Path

# Путь к Obsidian vault
VAULT_PATH = Path.home() / "Obsidian" / "FOL"

# Local REST API plugin
OBSIDIAN_API_URL = "https://127.0.0.1:27124"
OBSIDIAN_API_KEY = ""  # Из .env: OBSIDIAN_API_KEY

# API endpoints
ENDPOINTS = {
    "status": "/",
    "read_note": "/vault/{path}",
    "write_note": "/vault/{path}",
    "patch_note": "/vault/{path}",
    "delete_note": "/vault/{path}",
    "list_notes": "/vault/",
    "search": "/search/simple/",
    "command": "/commands/{commandId}/",
}

# SSL verification (self-signed cert)
VERIFY_SSL = False

# Default tags
DEFAULT_TAGS = ["fol", "auto-generated"]

# Frontmatter template
FRONTMATTER_TEMPLATE = """---
created: {created}
updated: {updated}
tags: [{tags}]
source: {source}
aliases: [{aliases}]
links: [{links}]
---
"""

# Vault structure (folders to create on init)
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
    "Archive",
]
```

### 5.3 `client.py` — HTTP клиент

```python
"""HTTP client for Obsidian Local REST API plugin."""

import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from obsidian.config import (
    OBSIDIAN_API_URL,
    OBSIDIAN_API_KEY,
    ENDPOINTS,
    VERIFY_SSL,
)

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    """Build auth headers."""
    return {
        "Authorization": f"Bearer {OBSIDIAN_API_KEY}",
        "Content-Type": "application/json",
    }


def _request(
    method: str,
    endpoint: str,
    path_params: dict[str, str] | None = None,
    body: Any = None,
) -> dict[str, Any]:
    """Make HTTP request to Obsidian REST API.
    
    Args:
        method: GET, PUT, PATCH, DELETE, POST
        endpoint: key from ENDPOINTS dict
        path_params: params to substitute in endpoint URL
        body: request body (dict or str)
    
    Returns:
        Parsed JSON response
    
    Raises:
        ObsidianConnectionError: if vault is unreachable
        ObsidianAuthError: if API key is invalid
        ObsidianNotFoundError: if note doesn't exist
    """
    url_template = ENDPOINTS.get(endpoint, endpoint)
    url = OBSIDIAN_API_URL + url_template
    
    if path_params:
        # Safe format — only substitute known params
        url = url.format(**path_params)
    
    data = None
    if body is not None:
        data = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
    
    req = urllib.request.Request(
        url,
        data=data,
        headers=_headers(),
        method=method,
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ObsidianAuthError("Invalid Obsidian API key") from e
        if e.code == 404:
            raise ObsidianNotFoundError(f"Note not found: {path_params}") from e
        raise ObsidianConnectionError(f"HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise ObsidianConnectionError(
            f"Cannot connect to Obsidian at {OBSIDIAN_API_URL}. "
            f"Is Obsidian running with Local REST API plugin enabled?"
        ) from e


def check_connection() -> bool:
    """Check if Obsidian vault is reachable."""
    try:
        resp = _request("GET", "status")
        return resp.get("status") == "ok"
    except (ObsidianConnectionError, ObsidianAuthError):
        return False


def read_note(vault_path: str) -> str:
    """Read a note's content.
    
    Args:
        vault_path: relative path in vault, e.g. "Projects/FOL/plan"
    """
    result = _request("GET", "read_note", path_params={"path": vault_path})
    return result.get("content", "")


def write_note(vault_path: str, content: str) -> dict[str, Any]:
    """Create or overwrite a note.
    
    Args:
        vault_path: relative path, e.g. "Ideas/new-feature"
        content: full markdown content
    """
    return _request("PUT", "write_note", path_params={"path": vault_path}, body=content)


def patch_note(
    vault_path: str,
    target_type: str,
    target: list[str],
    operation: str,
    content: str,
) -> dict[str, Any]:
    """Surgically modify a note at a specific heading/block.
    
    Args:
        vault_path: relative path
        target_type: "heading" | "block" | "frontmatter"
        target: ["My Section"] for heading
        operation: "append" | "replace" | "prepend"
        content: text to insert
    """
    body = {
        "targetType": target_type,
        "target": target,
        "operation": operation,
        "content": content,
    }
    return _request("PATCH", "patch_note", path_params={"path": vault_path}, body=body)


def delete_note(vault_path: str) -> dict[str, Any]:
    """Move a note to system trash."""
    return _request("DELETE", "delete_note", path_params={"path": vault_path})


def search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Full-text search across the vault.
    
    Returns:
        List of {path, filename, content, score} dicts
    """
    result = _request("POST", "search", body={"query": query, "limit": limit})
    return result.get("results", [])
```

### 5.4 `vault.py` — управление структурой

```python
"""Vault structure management — CRUD plus folder hierarchy."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from obsidian.client import write_note, read_note, patch_note, search
from obsidian.config import VAULT_PATH, VAULT_STRUCTURE, FRONTMATTER_TEMPLATE
from obsidian.linker import auto_link_note

logger = logging.getLogger(__name__)


def init_vault() -> None:
    """Create vault directory structure and _index.md files."""
    VAULT_PATH.mkdir(parents=True, exist_ok=True)
    
    for folder in VAULT_STRUCTURE:
        folder_path = VAULT_PATH / folder
        folder_path.mkdir(exist_ok=True)
        
        # Create _index.md if it doesn't exist
        index_path = f"{folder}/_index"
        try:
            read_note(index_path)
        except ObsidianNotFoundError:
            content = f"# {folder}\n\n*Авто-сгенерировано FOL.*\n"
            write_note(index_path, content)
            logger.info("Created _index.md for %s", folder)


def get_note(vault_path: str) -> str:
    """Read a note's markdown content."""
    return read_note(vault_path)


def save_note(
    vault_path: str,
    content: str,
    tags: list[str] | None = None,
    source: str = "orchestrator",
    auto_link: bool = True,
) -> dict[str, Any]:
    """Write a note with frontmatter and optional auto-linking.
    
    Args:
        vault_path: "Projects/FOL/new-feature"
        content: markdown body (without frontmatter)
        tags: ["project", "fol"]
        source: "orchestrator" | "user" | "agent"
        auto_link: run semantic linker after write
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_tags = (tags or []) + ["fol"]
    
    full_content = f"""---
created: {now}
updated: {now}
tags: [{', '.join(all_tags)}]
source: {source}
---

{content}
"""
    
    result = write_note(vault_path, full_content)
    
    if auto_link:
        asyncio.create_task(auto_link_note(vault_path, content))
    
    return result


def append_to_section(
    vault_path: str,
    section: str,
    content: str,
) -> dict[str, Any]:
    """Append content to a specific heading in a note.
    
    Args:
        vault_path: "Daily/2026-04-12"
        section: "Tasks" or "## Tasks"
        content: "- [ ] New task item"
    """
    return patch_note(
        vault_path=vault_path,
        target_type="heading",
        target=[section.lstrip("#").strip()],
        operation="append",
        content=f"\n{content}",
    )


def create_project(name: str, description: str) -> str:
    """Create a new project folder and index note.
    
    Returns:
        vault path to the project index, e.g. "Projects/My-Project"
    """
    project_slug = _slugify(name)
    vault_path = f"Projects/{project_slug}"
    
    content = f"""# {name}

{description}

## Статус
🟡 В разработке

## Tasks
- [ ] Initial setup

## Links
"""
    
    save_note(vault_path, content, tags=["project"])
    logger.info("Created project: %s", vault_path)
    return vault_path


def create_idea(title: str, body: str) -> str:
    """Create a new idea note."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = _slugify(title)
    vault_path = f"Ideas/{date}-{slug}"
    
    content = f"""# {title}

{body}

## Статус
💡 Idea

## Links
"""
    
    save_note(vault_path, content, tags=["idea"])
    return vault_path


def create_decision(title: str, context: str, decision: str, alternatives: list[str]) -> str:
    """Log an architectural decision."""
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = _slugify(title)
    vault_path = f"Decisions/{date}-{slug}"
    
    alts = "\n".join(f"- {a}" for a in alternatives)
    content = f"""# {title}

## Контекст
{context}

## Решение
{decision}

## Альтернативы
{alts}

## Статус
✅ Принято
"""
    
    save_note(vault_path, content, tags=["decision"])
    return vault_path


def ensure_daily_note(date: str | None = None) -> str:
    """Get or create today's daily note.
    
    Args:
        date: "2026-04-12" format. Defaults to today.
    
    Returns:
        Vault path to the daily note
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    vault_path = f"Daily/{date}"
    
    try:
        read_note(vault_path)
    except ObsidianNotFoundError:
        content = f"""# {date}

## 🎯 Goals for today
- 

## ✅ Done
- 

## 📝 Notes
- 

## 🔗 Links
"""
        save_note(vault_path, content, tags=["daily"])
        logger.info("Created daily note: %s", vault_path)
    
    return vault_path


def _slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    import re
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text
```

### 5.5 `linker.py` — Semantic Linker

```python
"""Semantic Linker — автоматическое создание связей между заметками."""

import json
import logging
from typing import Any

from obsidian.client import search, patch_note, read_note
from analyze._llm import llm_call_json

logger = logging.getLogger(__name__)

# LLM prompt for concept extraction
CONCEPT_EXTRACTION_PROMPT = """Extract the top 5 key concepts/entities from this note.
These will be used to find related notes. Return JSON array of strings.
Focus on: project names, technologies, people, architectural decisions, domain terms."""


LINK_DECISION_PROMPT = """Given a NEW note and a list of EXISTING notes from the vault, 
decide which links should be created between them.

For each link, choose a type:
- "related" — shares common topics
- "parent" — hierarchical parent
- "child" — hierarchical child  
- "source" — the existing note is a source/inspiration
- "implements" — this note implements an idea from the existing note
- "contradicts" — this note contradicts the existing note
- "follow_up" — follow-up or continuation

Return JSON array of: {{"target": "vault/path", "type": "link_type", "reason": "why"}}

NEW NOTE:
{new_content}

EXISTING NOTES:
{existing_notes}
"""


async def extract_concepts(content: str) -> list[str]:
    """Extract key concepts from note content using LLM."""
    try:
        result = llm_call_json(
            CONCEPT_EXTRACTION_PROMPT,
            content[:2000],  # Truncate for token limit
            max_tokens=200,
        )
        if isinstance(result, list):
            return [c for c in result if isinstance(c, str)][:5]
        return []
    except Exception as exc:
        logger.warning("Concept extraction failed: %s", exc)
        return []


async def auto_link_note(vault_path: str, content: str) -> list[dict[str, Any]]:
    """Find and create semantic links for a note.
    
    This runs after every write to the vault.
    
    Returns:
        List of created links: [{target, type, reason}]
    """
    # 1. Extract concepts
    concepts = await extract_concepts(content)
    if not concepts:
        logger.debug("No concepts extracted from %s", vault_path)
        return []
    
    # 2. Search for related notes
    related_notes = []
    for concept in concepts[:3]:  # Top 3 concepts
        results = search(concept, limit=5)
        for r in results:
            path = r.get("path", "")
            if path != vault_path and path not in [n["path"] for n in related_notes]:
                related_notes.append({
                    "path": path,
                    "content": r.get("content", "")[:500],
                    "score": r.get("score", 0),
                })
    
    if not related_notes:
        logger.debug("No related notes found for %s", vault_path)
        return []
    
    # 3. LLM decides on links
    existing_summary = "\n\n".join(
        f"--- {n['path']} ---\n{n['content']}"
        for n in related_notes[:10]  # Top 10 candidates
    )
    
    prompt = LINK_DECISION_PROMPT.format(
        new_content=content[:1000],
        existing_notes=existing_summary,
    )
    
    try:
        links = llm_call_json(prompt, "", max_tokens=500)
        if not isinstance(links, list):
            logger.warning("Linker returned non-list: %s", type(links))
            return []
    except Exception as exc:
        logger.warning("Link decision failed: %s", exc)
        return []
    
    # 4. Write links to the note
    if links:
        link_lines = ["\n## Связано с"]
        for link in links:
            target = link.get("target", "")
            link_type = link.get("type", "related")
            reason = link.get("reason", "")
            link_lines.append(f"- [[{target}]] → {link_type} ({reason})")
        
        link_section = "\n".join(link_lines)
        try:
            patch_note(
                vault_path=vault_path,
                target_type="heading",
                target=["Links"],
                operation="append",
                content=link_section,
            )
        except Exception as exc:
            logger.warning("Failed to add links to %s: %s", vault_path, exc)
    
    # 5. Update backlinks in target notes
    for link in links:
        target = link.get("target", "")
        if not target:
            continue
        try:
            backlink_line = f"- [[{vault_path}]] → {link.get('type', 'related')}"
            patch_note(
                vault_path=target,
                target_type="heading",
                target=["Links"],
                operation="append",
                content=f"\n{backlink_line}",
            )
        except Exception as exc:
            logger.debug("Backlink update skipped for %s: %s", target, exc)
    
    logger.info("Created %d links for %s", len(links), vault_path)
    return links
```

### 5.6 `sync.py` — синхронизация с `~/.secondself/`

```python
"""Two-way sync between ~/.secondself/ files and Obsidian vault."""

import logging
from pathlib import Path
from datetime import datetime, timezone

from obsidian.client import read_note, write_note
from obsidian.vault import save_note

logger = logging.getLogger(__name__)

MEMORY_DIR = Path.home() / ".secondself"
VAULT_PROFILE_DIR = "Profile"
VAULT_EPISODIC_DIR = "Episodic"

# Mapping: ~/.secondself/ file → Obsidian vault path
SYNC_MAP = {
    "identity.md": f"{VAULT_PROFILE_DIR}/identity",
    "preferences.md": f"{VAULT_PROFILE_DIR}/preferences",
    "episodic.md": f"{VAULT_EPISODIC_DIR}/events",
}


def sync_to_obsidian() -> dict[str, str]:
    """Sync all ~/.secondself/ files to Obsidian vault.
    
    One-way: .secondself → Obsidian.
    Obsidian is the source of truth for edits; .secondself is the source
    for machine-generated content (identity pipeline, episodic events).
    
    Returns:
        {filename: "synced" | "skipped" | "error"}
    """
    results = {}
    
    for filename, vault_path in SYNC_MAP.items():
        file_path = MEMORY_DIR / filename
        if not file_path.exists():
            results[filename] = "skipped (not found)"
            continue
        
        try:
            content = file_path.read_text(encoding="utf-8")
            # Add frontmatter
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            full = f"""---
created: {now}
updated: {now}
tags: [fol, synced, {Path(filename).stem}]
source: identity-pipeline
---

{content}
"""
            write_note(vault_path, full)
            results[filename] = "synced"
            logger.info("Synced %s → Obsidian %s", filename, vault_path)
        except Exception as exc:
            results[filename] = f"error: {exc}"
            logger.error("Failed to sync %s: %s", filename, exc)
    
    return results


def sync_from_obsidian(target_file: str) -> bool:
    """Sync a single file from Obsidian back to ~/.secondself/.
    
    Useful when user edits a note in Obsidian and we want to
    incorporate those changes.
    
    Args:
        target_file: "identity.md" | "preferences.md" | "episodic.md"
    
    Returns:
        True if synced successfully
    """
    vault_path = SYNC_MAP.get(target_file)
    if not vault_path:
        logger.warning("Unknown sync target: %s", target_file)
        return False
    
    try:
        content = read_note(vault_path)
        # Strip frontmatter if present
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()
        
        file_path = MEMORY_DIR / target_file
        file_path.write_text(content, encoding="utf-8")
        logger.info("Synced from Obsidian: %s → ~/.secondself/%s", vault_path, target_file)
        return True
    except Exception as exc:
        logger.error("Failed to sync from Obsidian %s: %s", vault_path, exc)
        return False
```

### 5.7 `tools.py` — инструменты для FOL

```python
"""Obsidian tool definitions for the FOL agent (Anthropic format).

These tools are added to ALL_TOOLS in orchestrator/server.py.
"""

OBSIDIAN_TOOLS = [
    {
        "name": "obsidian_read",
        "description": "Read a note from the Obsidian vault by path. "
                       "Use this to load project docs, decisions, knowledge.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Vault path, e.g. 'Projects/FOL/architecture'"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "obsidian_write",
        "description": "Create or overwrite a note in the Obsidian vault. "
                       "Automatically creates semantic links to related notes. "
                       "Use this to save plans, summaries, new knowledge.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Vault path, e.g. 'Knowledge/obsidian-api'"},
                "content": {"type": "string", "description": "Markdown content"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "obsidian_search",
        "description": "Full-text search across the entire vault. "
                       "Use this to find relevant prior knowledge, decisions, or projects.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "obsidian_create_project",
        "description": "Create a new project folder with an index note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "description": {"type": "string", "description": "Brief description"},
            },
            "required": ["name", "description"],
        },
    },
    {
        "name": "obsidian_log_decision",
        "description": "Log an architectural or design decision with context and alternatives.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Decision title"},
                "context": {"type": "string", "description": "Why this decision was needed"},
                "decision": {"type": "string", "description": "What was decided"},
                "alternatives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Alternative approaches considered",
                },
            },
            "required": ["title", "context", "decision", "alternatives"],
        },
    },
    {
        "name": "obsidian_save_idea",
        "description": "Save a new idea to the vault. Automatically linked to existing projects.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Idea title"},
                "body": {"type": "string", "description": "Idea description"},
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "obsidian_daily_log",
        "description": "Log an entry to today's daily note under a section (Tasks, Notes, Done).",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "Section name: Tasks, Done, Notes"},
                "content": {"type": "string", "description": "Content to append"},
            },
            "required": ["section", "content"],
        },
    },
    {
        "name": "obsidian_sync_profile",
        "description": "Sync identity, preferences, and episodic files from ~/.secondself/ to Obsidian.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]
```

---

## 6. ИНТЕГРАЦИЯ С ORCHESTRATOR

### 6.1 Добавление в `orchestrator/server.py`

```python
# В imports добавить:
from obsidian.tools import OBSIDIAN_TOOLS
from obsidian.client import check_connection

# Добавить к ALL_TOOLS:
ALL_TOOLS = BROWSER_TOOLS + DESKTOP_TOOLS + UI_TOOLS + PRODUCTIVITY_TOOLS + OBSIDIAN_TOOLS

# В lifespan() добавить проверку Obsidian:
obsidian_connected = check_connection()
print(f"[orchestrator] Obsidian vault: {'connected' if obsidian_connected else 'disconnected'}")

# В execute_tool_call() добавить маршрутизацию:
if tool_name.startswith("obsidian_"):
    return await execute_obsidian_tool(tool_name, arguments)
```

### 6.2 Добавление в `build_system_prompt()`

```python
# В system prompt добавить секцию OBSIDIAN KNOWLEDGE:
obsidian_section = ""
try:
    from obsidian.bridge import get_context_for_prompt
    obsidian_section = get_context_for_prompt(
        active_project="Projects/FOL",  # Определяется из контекста
        n_recent=5,
    )
except Exception:
    obsidian_section = ""

if obsidian_section:
    sections.append(f"OBSIDIAN KNOWLEDGE (recent notes):\n{obsidian_section}")
```

### 6.3 Добавление в `.env`

```env
# Obsidian Local REST API
OBSIDIAN_VAULT_PATH=~/Obsidian/FOL
OBSIDIAN_API_KEY=your-api-key-here
```

---

## 7. САМОАНАЛИЗ (POST-TASK LOGGING)

После каждой задачи FOL записывает в Obsidian:

```markdown
# Самоанализ задачи: [summary]

**Дата:** 2026-04-12 14:30
**Задача:** [описание задачи]
**Статус:** ✅ / ❌

## Что получилось
- ...

## Ошибки
- ...

## Что улучшить
- ...

## Чему научился
- ...

## Связано с
- [[Conversations/2026-04-12-task-context]]
- [[Projects/FOL/obsidian-memory]]
```

Файл сохраняется в `Decisions/retrospectives/YYYY-MM-DD-task-slug.md`.

---

## 8. ИНИЦИАЛИЗАЦИЯ

### 8.1 Первый запуск

```bash
# 1. Установить плагин Obsidian Local REST API
#    Settings → Community Plugins → Browse → "Local REST API"

# 2. Создать vault (если нет)
mkdir -p ~/Obsidian/FOL
# Открыть Obsidian → "Open folder as vault" → ~/Obsidian/FOL

# 3. Включить Local REST API
#    Settings → Local REST API → Enable → Copy API Key

# 4. Добавить API ключ в .env
echo "OBSIDIAN_API_KEY=ваш-ключ" >> .env

# 5. Инициализировать структуру vault
python -c "from obsidian.vault import init_vault; init_vault()"

# 6. Синхронизировать существующие профили
python -c "from obsidian.sync import sync_to_obsidian; print(sync_to_obsidian())"
```

### 8.2 Проверка соединения

```python
from obsidian.client import check_connection
print("Obsidian connected:", check_connection())
# → True если Obsidian запущен и плагин активен
```

---

## 9. ПОРЯДОК РЕАЛИЗАЦИИ (BUILD ORDER)

1. **`obsidian/config.py`** — конфигурация, пути, endpoint'ы
2. **`obsidian/client.py`** — HTTP клиент с обработкой ошибок
3. **`obsidian/vault.py`** — CRUD, `init_vault()`, `create_project()`, `ensure_daily_note()`
4. **`obsidian/search.py`** — поиск по vault
5. **`obsidian/linker.py`** — Semantic Linker (LLM-связи)
6. **`obsidian/sync.py`** — синхронизация с `~/.secondself/`
7. **`obsidian/tools.py`** — инструменты для FOL
8. **`obsidian/daily.py`** — ежедневные заметки
9. **Интеграция в `orchestrator/server.py`** — добавить инструменты + маршрутизацию
10. **Тесты** — unit-тесты для каждого модуля (mock REST API)
11. **Обновление `FOL_UPGRADE.md`** — отметить Phase 6 как начатую

---

## 10. ЭКОСИСТЕМА (БУДУЩЕЕ)

После базовой интеграции:

| Фича | Описание |
|------|----------|
| **Obsidian Graph View** | FOL показывает граф в VNC PiP |
| **Obsidian Sync** | Vault синхронизируется на iPhone через iCloud |
| **Canvas** | FOL рисует архитектурные схемы в Obsidian Canvas |
| **Kanban** | FOL управляет Projects через Obsidian Kanban |
| **Templates** | FOL использует шаблоны Obsidian для структуры заметок |
| **Git Auto-commit** | Автокоммит vault в GitHub каждую ночь |

---

*FOL Layer 5 — Semantic Memory. Obsidian как мозг ассистента.*
*Связи между заметками = связи между мыслями.*
