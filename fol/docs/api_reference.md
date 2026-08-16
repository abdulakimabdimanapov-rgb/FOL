# F.O.L. API Reference

## REST API

FOL exposes a REST API for programmatic access.

### Base URL

```
http://127.0.0.1:8754
```

### Endpoints

#### Health Check

```
GET /health
```

Response:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime": 123.45,
  "modules": {"llm": "active", "tools": "active"}
}
```

#### Conversation

```
POST /conversation/send
Content-Type: application/json

{"message": "Hello FOL"}
```

```
GET /conversation/history?limit=50
```

```
DELETE /conversation/history
```

#### Memory

```
POST /memory/store
Content-Type: application/json

{"content": "Remember this", "metadata": {"type": "note"}}
```

```
POST /memory/retrieve
Content-Type: application/json

{"query": "What did I say about...?", "limit": 5}
```

```
DELETE /memory/{memory_id}
```

#### Tools

```
GET /tools/
```

```
POST /tools/{tool_name}/execute
Content-Type: application/json

{"params": {"command": "ls -la"}}
```

```
GET /tools/openai-format
```

#### Plugins

```
GET /plugins/
```

```
POST /plugins/{plugin_name}/enable
```

```
POST /plugins/{plugin_name}/disable
```

#### Settings

```
GET /settings/
```

```
PATCH /settings/
Content-Type: application/json

{"debug": true, "log_level": "DEBUG"}
```

### WebSocket

Connect to `ws://127.0.0.1:8754/ws` for real-time communication.

**Events:**
- `user_input` — Send a message
- `llm_token` — Streaming token from LLM
- `llm_response` — Complete response
- `tool_executed` — Tool execution result
- `error` — Error event

**Example:**
```json
// Send
{"type": "user_input", "payload": {"text": "Hello"}}

// Receive
{"type": "llm_response", "payload": {"response": "Hello! How can I help?"}}
```
