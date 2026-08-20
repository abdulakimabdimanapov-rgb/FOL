# Freebuff Tmux Bridge

Integration between FOL and Freebuff CLI via persistent tmux session.

## Architecture

```
FOL
 ↓
FreebuffTmuxBridge (BrainInterface)
 ↓
FreebuffTmuxSession (tmux session management)
 ↓
tmux send-keys / capture-pane
 ↓
Freebuff TUI (inside tmux)
 ↓
Response
 ↓
FreebuffTmuxParser (ANSI/TUI cleanup)
 ↓
FOL Core
```

## Files

| File | Purpose |
|------|---------|
| `fol/modules/brain/freebuff_tmux_bridge.py` | BrainInterface implementation — the entry point |
| `fol/modules/brain/freebuff_tmux_session.py` | tmux session lifecycle, send/receive, state machine |
| `fol/modules/brain/freebuff_tmux_parser.py` | Clean ANSI/TUI artifacts, extract clean text |
| `fol/modules/brain/session_keepalive.py` | Background watchdog, auto-restart on crash |

## Message Flow

```
1. FOL calls bridge.chat() / chat_stream() / acomplete()
2. Bridge builds prompt from messages
3. Bridge acquires _request_lock (serializes concurrent calls)
4. Bridge calls session.send_message(text)
5. Session uses bracketed paste: ESC[200~ ... text ... ESC[201~ + Enter
6. Session calls session.read_response()
7. Session polls tmux capture-pane every 0.5s
8. Parser cleans ANSI, box-drawing, spinners, TUI chrome
9. Parser deduplicates consecutive identical lines
10. Session tracks CompletionState: SUBMITTED → WORKING → RESPONDING → COMPLETE
11. When output settles (no changes for settle_ms) + no thinking patterns → COMPLETE
12. Bridge returns clean text to FOL
```

## Completion State Machine

```
IDLE → SUBMITTED → WORKING → RESPONDING → COMPLETE → IDLE
                                                         ↓
                                                     (next message)
```

- **IDLE**: Session ready, no request in flight
- **SUBMITTED**: Message sent, waiting for Freebuff to start processing
- **WORKING**: Freebuff acknowledged input, actively processing
- **RESPONDING**: Output is streaming back
- **COMPLETE**: Response fully received, ready to extract
- **ERROR**: Unrecoverable error

## send_message

```python
async def send_message(text: str) -> bool
```

1. Checks tmux session exists
2. Rejects if session is BUSY (concurrent protection)
3. Takes snapshot of current pane output (for diffing)
4. Sets state to SUBMITTED
5. Sends via bracketed paste (ESC[200~ ... text ... ESC[201~ + Enter)
6. Returns True on success, False on failure

**Bracketed paste** is always used because:
- Freebuff is a TUI — special characters could trigger shortcuts
- Multi-line text needs proper handling
- It's the safest approach for any TUI

## capture_output

```python
capture_pane(name: str, start_line: int = -500) -> str
```

Uses `tmux capture-pane -t <session> -p -S -500` to capture the rendered screen content.

Returns the raw terminal output (before parser cleanup).

## Parser

The parser (`freebuff_tmux_parser.py`) cleans raw tmux output:

### Cleanup Pipeline

```
raw tmux output
  → strip_bracketed_paste()     # Remove ESC[200~ / ESC[201~
  → strip_ansi()                # Remove ANSI escape sequences
  → strip_control_chars()       # Remove control characters
  → strip_box_drawing()         # Remove Unicode box-drawing
  → dedup_lines()               # Remove consecutive identical lines
  → normalize_whitespace()      # Collapse whitespace, trim lines
```

### Response Extraction

`extract_response()` additionally:
- Filters out prompt characters (❯, >, ▶, etc.)
- Filters out spinner characters (⠋⠙⠹⠸...)
- Filters out TUI status prefixes (●, ○, ◉, etc.)
- Filters out user's input echo
- Filters out decorative lines (───, ===, etc.)
- Returns clean assistant text

## Completion Detection

`detect_response_complete()` uses multiple signals:

1. **Idle pattern visible** (prompt returned) — strongest signal
2. **No thinking indicators** (thinking, analyzing, processing, etc.)
3. **No spinner characters** in raw output
4. **Substantial content** (3+ lines) with no thinking

Settle detection: output must be unchanged for `settle_ms` (default 1500ms).

## Persistent Session

One Freebuff process serves ALL requests:

```
start FOL
  ↓
start Freebuff (once)
  ↓
message 1 → response 1
  ↓
message 2 → response 2
  ↓
message 3 → response 3
```

Freebuff is NOT restarted between messages. This preserves conversation context.

## Concurrent Request Handling

Only ONE message at a time:

```python
# Bridge level
self._request_lock = asyncio.Lock()  # Serializes all requests

# Session level
self._lock = asyncio.Lock()          # Serializes send/receive
```

If a second request arrives while the first is in flight:
- The second request **waits** for the lock (not rejected)
- `_busy` flag tracks current state
- `status()` returns `busy: true/false`

## Error Handling

| Error | Behavior |
|-------|----------|
| tmux not installed | `BrainUnavailableError` → fallback to `current` |
| Freebuff binary not found | `BrainUnavailableError` → fallback |
| Session creation failed | `BrainUnavailableError` → fallback |
| Freebuff not ready | `BrainUnavailableError` → fallback |
| Response empty | `BrainError` → retry or fallback |
| Response timeout | Partial response if available, else `BrainError` |
| Session crashed | Keepalive auto-restarts (up to 5 times) |

## Fallback Chain

```
freebuff_tmux
  ↓ (on failure)
current (LiteLLM)
  ↓ (on failure)
API providers (OpenRouter, OpenAI, Anthropic, ...)
```

Configured via `FOL_BRAIN=freebuff_tmux` in `.env`.

## Keepalive Watchdog

`SessionKeepalive` runs in background:
- Checks tmux session existence every 10s
- Checks `capture-pane` responsiveness
- After 3 missed checks → calls restart callback
- Bridge provides restart callback that calls `session.restart()`
- Max 5 auto-restarts with 5s cooldown

## Configuration

```env
# Select brain backend
FOL_BRAIN=freebuff_tmux

# Freebuff binary
FREEBUFF_BINARY=freebuff
FREEBUFF_CWD=/path/to/project

# tmux session
FREEBUFF_TMUX_SESSION=fol-freebuff
FREEBUFF_TMUX_COLS=120
FREEBUFF_TMUX_ROWS=40

# Timeouts
FREEBUFF_START_TIMEOUT=15       # seconds to wait for Freebuff ready
FREEBUFF_RESPONSE_TIMEOUT=300   # seconds to wait for response
FREEBUFF_SETTLE_MS=1500         # ms of silence = response complete

# Restart
FREEBUFF_RESTART_ATTEMPTS=2     # max restart attempts on crash
FREEBUFF_RESTART_DELAY=2        # seconds between restart attempts
```

## Safety

- Freebuff does NOT get direct access to system tools
- All tool calls go through FOL's ToolRegistry → RiskScorer → ConfirmationGate
- API keys and secrets are never logged
- The bridge only manages tmux I/O — no fake HTTP APIs
- Session keepalive never exits the current Freebuff session
