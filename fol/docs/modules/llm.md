# LLM Module

## Overview

The LLM module handles interaction with language models, including local MLX inference and cloud APIs.

## Components

| Component | Description |
|-----------|-------------|
| `LLMEngine` | Central engine managing backends |
| `MLXBackend` | Local MLX inference |
| `OpenAIBackend` | OpenAI API |
| `AnthropicBackend` | Anthropic API |
| `GeminiBackend` | Google Gemini API |
| `Agent` | ReAct agent for multi-step reasoning |
| `PromptManager` | Template management |
| `ModelRouter` | Complexity-based routing |
| `FunctionCalling` | Tool use via function calling |

## API

### LLMEngine

```python
from modules.llm.engine import LLMEngine

engine = LLMEngine(config={"llm_model": "...", "llm_backend": "mlx"})
await engine.initialize()
response = await engine.generate("Hello, how are you?")
```

### Agent

```python
from modules.llm.agent import Agent

agent = Agent(llm=engine, tools=tool_registry)
response = await agent.run("Open Safari and search for recipes")
```

## Pipeline

```
User Input → Context Assembly → RAG Retrieval
  → System Prompt + Memory → LLM call
  → Response → [Event: LLM_RESPONSE_READY]
```

## Configuration

```bash
FOL_LLM_BACKEND=mlx        # mlx | openai | anthropic | gemini
FOL_LLM_MODEL=...          # Model identifier
FOL_LLM_MAX_TOKENS=4096
FOL_LLM_TEMPERATURE=0.7
```
