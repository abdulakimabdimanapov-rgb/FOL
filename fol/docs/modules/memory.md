# Memory Module

## Overview

The Memory module provides short-term and long-term memory for FOL.

## Components

| Component | Description |
|-----------|-------------|
| `VectorStore` | ChromaDB-based vector search |
| `ConversationHistory` | Conversation history (JSONL + SQLite) |
| `KnowledgeGraph` | Semantic relationships between entities |
| `EpisodicMemory` | "What happened when" memory |
| `PreferencesStore` | User preferences |
| `RAGPipeline` | Retrieval-Augmented Generation |

## Memory Types

| Type | Storage | Duration | Content |
|------|---------|----------|---------|
| Working Memory | In-memory | Session | Current context |
| Conversation | JSONL + ChromaDB | Permanent | All dialogs |
| Episodic | JSONL | Permanent | Events with timestamps |
| Semantic | Knowledge Graph | Permanent | Facts and relationships |
| Preferences | SQLite | Permanent | User settings |

## API

### VectorStore

```python
from modules.memory.vector_store import VectorStore

store = VectorStore()
await store.initialize()
await store.add(content="Important fact", metadata={"source": "conversation"})
results = await store.search(query="What fact?", limit=5)
```

### ConversationHistory

```python
from modules.memory.conversation import ConversationHistory

history = ConversationHistory()
await history.initialize()
await history.add_turn(user="Hello", assistant="Hi there!")
turns = await history.get_recent(limit=10)
```

## Configuration

```bash
FOL_MEMORY_VECTOR_DB_PATH=~/.fol/vector_db
FOL_MEMORY_MAX_RESULTS=10
```
