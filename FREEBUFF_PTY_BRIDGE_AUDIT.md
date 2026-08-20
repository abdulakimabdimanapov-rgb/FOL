# FREEBUFF_PTY_BRIDGE_AUDIT.md

> Audit date: 2026-08-18
> Goal: Understand existing Freebuff integration and plan PTY Bridge architecture

---

## 1. Current Freebuff Integration

### What exists today

| Component | File | Purpose |
|-----------|------|---------|
| `FreebuffBrainAdapter` | `fol/modules/brain/freebuff_adapter.py` | Routes reasoning through OpenRouter to Freebuff's models (DeepSeek V4 Flash, MiMo 2.5). **NOT a real Freebuff CLI bridge** — it's a model provider adapter. |
| `FreebuffProcessManager` | `fol/modules/brain/freebuff_process.py` | Monitors OpenRouter health. Does NOT spawn processes. |
| `BrainStartupManager` | `fol/modules/brain/startup.py` | Initializes brain chain: Freebuff (via OpenRouter) → Current (fallback). |
| `FreebuffBrainAdapter` (LLM layer) | `fol/modules/llm/brain.py` | Honest placeholder — `available=False`, raises `BrainUnavailableError`. |
| `BrainInterface` | `fol/modules/llm/brain.py` | Canonical reasoning contract: `chat()`, `chat_stream()`, `acomplete()`, `classify()`, `plan()`, `select_tools()`, `summarize()`, `verify()`. |
| `BrainRouter` | `fol/modules/llm/brain_router.py` | Composes multiple brains with fallback. |
| `get_brain()` | `fol/modules/llm/brain.py` | Factory: `current` → `CurrentLLMAdapter`, `freebuff` → `BrainRouter([FreebuffAdapter, Current])`, `codebuff` → `BrainRouter([Codebuff, Current])`. |

### Key design decision: NOT deleting existing code
The `FreebuffBrainAdapter` (OpenRouter-based) is the **Freebuff Model Provider**.
The new `FreebuffBridgeCLI` will be the **Freebuff CLI Brain**.
They serve different purposes and coexist.

---

## 2. Freebuff CLI — How It Works

### Binary
- **Location**: `~/.config/manicode/freebuff` (Mach-O 64-bit arm64)
- **Wrapper**: `/Users/abulakimabdimanapov/.nvm/versions/node/v24.18.0/bin/freebuff` → `freebuff/index.js` → `freebuff/launcher.js` → spawns native binary
- **Version**: 0.0.124 (npm) / 0.0.150 (--version)
- **Installed globally via npm**: `freebuff@0.0.124`

### CLI flags
```
freebuff [options] [command]
  --continue [conversation-id]   Continue from a previous conversation
  --cwd <directory>              Set the working directory (default: cwd)
  -v, --version                  Print version
  -h, --help                     Show help
```

**No `--json`, `--non-interactive`, `--pipe`, or `--batch` mode.**

### TUI behavior
- Uses **alternate screen** (`\x1b[?1049h` / `\x1b[?1049l`)
- Uses **raw mode** (`stdin.setRawMode(true)`)
- Uses **mouse tracking** (`\x1b[?1000h`, `\x1b[?1002h`, `\x1b[?1003h`, `\x1b[?1006h`)
- Uses **bracketed paste** (`\x1b[?2004h`)
- Uses **cursor hide/show** (`\x1b[?25l`, `\x1b[?25h`)
- Spawned with `stdio: 'inherit'` — expects a real terminal

### Cannot be piped
```bash
echo "hello" | freebuff  # FAILS — TUI expects a real terminal
```

**Conclusion**: Must use PTY (pseudo-terminal) to interact with Freebuff CLI.

---

## 3. PTY Approach

### Python `pty` module
```python
import pty, os, select, time

master_fd, slave_fd = pty.openpty()
pid = os.fork()
if pid == 0:
    os.close(master_fd)
    os.dup2(slave_fd, 0)  # stdin
    os.dup2(slave_fd, 1)  # stdout
    os.dup2(slave_fd, 2)  # stderr
    os.execvp("freebuff", ["freebuff", "--cwd", "/path/to/project"])
else:
    os.close(slave_fd)
    # Read/write via master_fd
```

### Challenges
1. **Alternate screen**: freebuff switches to alternate screen on startup. Raw PTY output contains `\x1b[?1049h` and lots of screen-drawing codes.
2. **Ready detection**: No reliable "ready" prompt in the output. Need to detect when the TUI has finished initial setup.
3. **Response parsing**: Output contains spinners, progress UI, cursor movements, screen redraws. Must distinguish assistant response from UI noise.
4. **Multi-turn**: freebuff maintains session context natively via `--continue`. But we need to detect when a response is complete.

---

## 4. Proposed Architecture

```
FreebuffBridgeCLI (BrainInterface)
    │
    ├── FreebuffProcessManager (PTY-aware)
    │       is_installed()
    │       is_running()
    │       start()
    │       stop()
    │       restart()
    │       health()
    │
    ├── FreebuffSession
    │       process: subprocess
    │       master_fd: int
    │       pid: int
    │       state: BridgeState
    │       session_id: str
    │       cwd: str
    │       created_at: float
    │       last_activity: float
    │
    ├── FreebuffParser
    │       strip_ansi(text) → str
    │       normalize_terminal(text) → str
    │       detect_ready(raw_output) → bool
    │       detect_response_complete(raw_output, since) → bool
    │       extract_response(raw_output) → str
    │
    └── FreebuffBridgeCLI (BrainInterface)
            chat() → str
            chat_stream() → AsyncIterator
            acomplete() → dict
            classify(), plan(), select_tools(), summarize(), verify()
```

---

## 5. Files to Create

| File | Purpose |
|------|---------|
| `fol/modules/brain/freebuff_bridge.py` | Main bridge — BrainInterface implementation via PTY |
| `fol/modules/brain/freebuff_session.py` | PTY session management |
| `fol/modules/brain/freebuff_parser.py` | ANSI cleaning and response extraction |
| `fol/tests/brain/test_freebuff_bridge.py` | Test suite |
| `docs/freebuff-bridge.md` | Documentation |

---

## 6. Files to Modify

| File | Change |
|------|--------|
| `fol/modules/llm/brain.py` | Add `freebuff_cli` to `get_brain()` factory |
| `fol/modules/llm/freebuff.py` | Add `freebuff_cli_config()` for PTY bridge config |
| `fol/modules/brain/__init__.py` | Export new modules |
| `.env.template` | Add `FOL_BRAIN=freebuff_cli` and PTY config vars |
| `fol/config/settings.py` | Add PTY bridge settings |

---

## 7. Tests Required

1. Freebuff installation detection
2. PTY session creation
3. Process startup
4. Ready handshake
5. Send message
6. Receive response
7. ANSI cleanup
8. Prompt detection
9. Response complete detection
10. Streaming (chunked output)
11. Multi-turn session
12. Timeout handling
13. Process crash recovery
14. Automatic restart
15. Graceful shutdown
16. Fallback to CurrentLLMAdapter
17. Concurrent request handling
18. Cancellation
19. Working directory
20. Security checks (no key logging)

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| freebuff TUI output too complex to parse | Conservative extraction: wait for output to settle, strip ANSI, take last non-empty block |
| Freebuff session state conflicts with FOL state | FOL maintains own conversation history; Freebuff is only a Brain provider |
| PTY memory/performance overhead | Single persistent session, no per-message processes |
| Freebuff binary crashes mid-session | Detect exit, attempt restart, fallback to API brain |
| Freebuff CLI updates break PTY interaction | Version pinning in config, graceful degradation |
| Security: PTY captures all terminal output | Never log raw PTY output; only extract clean response text |
