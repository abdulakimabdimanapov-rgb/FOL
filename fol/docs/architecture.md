# FOL Architecture

## Overview

FOL follows a modular, event-driven architecture with clear separation of concerns.

## Core Components

### Event Bus
Asynchronous pub/sub system for inter-module communication. All modules communicate through events, not direct references.

### Orchestrator
Central dispatcher that routes user input through the pipeline: Input → Context → LLM → Tools → Output.

### Lifecycle Manager
Manages application state transitions (Created → Starting → Running → Stopping → Stopped) with startup/shutdown hooks.

## Module System

Each module implements an abstract base class and can be independently loaded/unloaded:

- **Input Modules**: Text, Speech, Screen Capture, Vision
- **LLM Module**: Multi-backend (MLX, OpenAI, Anthropic) with automatic failover
- **Memory Module**: Vector store, conversation history, knowledge graph, preferences
- **Tools Module**: System commands, mouse/keyboard, browser, clipboard
- **Output Module**: TTS, display, notifications
- **Plugin Module**: Dynamic loading, hooks, enable/disable

## Data Flow

```
User Input
  → Input Module (text/speech/screen)
  → Orchestrator
  → Context Manager (recent history)
  → RAG Pipeline (vector search + KG + prefs)
  → Plugin Hooks (before_llm)
  → LLM Engine (model router → backend)
  → Plugin Hooks (after_llm)
  → Tool Execution (if needed)
  → Output Module (TTS/display)
  → Memory Store (conversation + facts)
```

## Plugin System

Plugins extend FOL through hooks:
- `on_user_input` — modify input before LLM
- `before_llm_call` — modify messages before LLM
- `after_llm_response` — modify response after LLM
- `on_event` — react to any system event

## Security

- Command validation with blocklist
- Secret detection and masking
- Rate limiting
- Circuit breaker for fault tolerance
