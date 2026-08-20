# FOL — Personal AI Assistant for macOS

> **v1.2.0** — Production-ready release: **1073+ tests passing**, brain backends (Codebuff/Freebuff), security hardening (race condition, shell injection, memory leak fixes).

FOL is a **digital twin**: an AI assistant that lives in your MacBook's notch, understands screen context, remembers you, and performs actions on your computer.

**The problem FOL solves:** everyday computer work is full of repetitive actions, re-explaining context, and constant app-switching — that's "friction" stealing your time.

**Solution — three pillars:**

| Pillar | What it does |
|---|---|
| **1. Desktop automation** | FOL opens apps, searches the browser, works with files and clicks — you stop wasting time on repetitive macOS tasks |
| **2. Context + Memory** | FOL remembers context and preferences — no need to explain the same thing over and over |
| **3. Proactive assistance** | FOL notices useful context on its own and suggests actions without waiting for a command |

---

## Quick Start

```bash
# 1. Set up .env (see .env.template — keys are empty, safe to share)
cp .env.template .env

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start all services
./run_all.sh

# 4. Verify
curl http://localhost:8420/status     # Orchestrator
curl http://localhost:8421/health     # Agent Server (desktop control)
curl http://localhost:8754/health     # FOL API (JARVIS commands)
```

Start individually: `./run_all.sh orchestrator | agent | fol | swift | web`.

### Policy: FOL Does NOT Use Local LLMs

> **We deliberately chose against local AI (Ollama, MLX inference, local model files, local fallback providers).** FOL doesn't run models on your hardware, doesn't heat up your Mac, and doesn't eat its memory — all reasoning happens through cloud APIs (Freebuff / OpenRouter / OpenAI / Anthropic). Only local STT (mlx-whisper) stays for speech recognition — that's not an LLM.

### LLM — One Line in `.env` (API Providers Only)

```env
LLM_MODEL=openrouter/nvidia/nemotron-3-super-120b-a12b:free
# or LLM_MODEL=openai/gpt-4o-mini, LLM_MODEL=claude-sonnet-4-20250514
LLM_FALLBACK_MODELS=openrouter/nvidia/nemotron-3-ultra-550b-a55b:free   # fallback chain
FOL_BRAIN=current        # current = LiteLLMRouter (API-only) | freebuff = Freebuff Brain
```

If the primary model is unavailable (quota/outage), the assistant automatically tries models from `LLM_FALLBACK_MODELS` in order — the system works as long as at least one model is reachable. Local models (`ollama/…`, MLX) are automatically excluded from the chain (re-enable only with explicit `FOL_ENABLE_LOCAL_LLM=1` — not recommended).

---

## Demo Scenarios (Verified End-to-End)

```bash
./scripts/demo.sh                  # 5 scenarios with pauses for recording
DEMO_QUICK=1 ./scripts/demo.sh     # no pauses (quick check)
./scripts/verify_scenarios.sh      # auto-verify scenarios
python3 scripts/e2e_check.py       # E2E: services + health + MJPEG + SSE
```

| Scenario | How it works |
|---|---|
| "Open Safari and find OpenAI news" | Opens Safari → searches → summary |
| "Write a letter to the professor" | Contact / Google OAuth |
| "Create a calendar event" | `create_event` via Google Calendar |
| "Open the FOL project" | Finder + keyboard commands |
| "Remember to send the report tomorrow" | `save_to_obsidian` → live memory |

---

## Architecture

```
User (Notch UI / Web / Voice)
      │
      ▼
Orchestrator (FastAPI, :8420)
      │   Router with 6 agents (General/Architect/Coder/Reviewer/Researcher/Memory)
      │   Two-stage tool selection (category → 5-12 from 50)
      │   Loop guard (anti-cycling protection)
      ▼
LLM (LiteLLM: OpenRouter / OpenAI / Anthropic / …) — model fallback chain
      │   tool calls
      ▼
Execution: Agent Server (:8421, desktop/browser) · Productivity (Gmail/Calendar)
           · Obsidian (memory) · FOL API (:8754, JARVIS)
      │
      ▼
Result → LLM → final answer (SSE streaming to UI)
```

Key mechanisms:
- **ToolRegistry** (`fol/modules/tools/registry.py`) — single registry for all 50 tools: schema, risk, confirmation.
- **ConfirmationGate** (`fol/modules/tools/gate.py`) — code decides, never the model: dangerous actions are blocked until user confirms; confirmation is bound to the exact call signature.
- **Two-stage tool selection** — the model sees 5–12 relevant tools, not all 50.
- **Loop guard** — repeated identical calls N times are interrupted.
- **Memory** — identity / preferences / episodic + Obsidian vault + daily tracker; context is injected into every LLM request.
- **Proactive Mode** — `suggestion_engine` (profile/pattern/ambient) + ambient cycle 30s + `proactive on/off` toggle in FOL API.
- **Security** — `.env` is not tracked by Git, secrets are scrubbed from logs and dashboard, unknown tools are rejected (fail closed).

## Project Structure

```
fol/                       # Python AI core (JARVIS API :8754)
  ├── core/ modules/ api/ config/ plugins/ tests/
orchestrator/              # FastAPI AI server (:8420): agents, tools, memory
agent-server/              # Desktop/browser control (:8421)
fol-app/                   # SwiftUI macOS app (Notch UI, voice)
src/                       # Next.js web interface (SSE chat)
auth/ fetch/ analyze/ clean/ utils/ context_engine/ obsidian/ dashboard/
cookie_sync/ bridge/ setup/ scripts/ tests/ docs/
run_all.sh                 # Unified launcher for all services
```

## Ports

| Port | Service |
|------|---------|
| 8420 | Orchestrator (AI server, SSE) |
| 8421 | Agent Server (desktop/browser) |
| 8754 | FOL API (JARVIS commands) |
| 3000 | Next.js web |

---

## Tests

```bash
# Run all tests
python -m pytest tests/ -v          # 1073+ passed (FOL core)
python3 -m pytest fol/tests/ -v     # Full FOL test suite

# Bilingual router (Russian + English)
python3 -m pytest tests/test_router.py -v -k "russian"
python3 -m pytest tests/test_router.py -v -k "bilingual"
python3 -m pytest tests/test_router.py -v -k "fuzzy"

# Text normalization
python3 -m pytest tests/test_normalize.py -v -k "russian"

# Swift build
cd fol-app && swift build
```

---

## Bilingual Routing (Russian + English)

FOL understands both Russian and English commands with a sophisticated routing pipeline:

```
User input → Greeting detection → Bilingual split → Keyword match → Fuzzy match → History → General
```

| Agent | EN keywords | RU keywords |
|-------|------------|-------------|
| **Architect** | architecture, design pattern, system design, roadmap | архитектур, спроектир, схема, тз |
| **Reviewer** | review, check, code review, audit, vulnerability | провер, ревью, качеств, аудит |
| **Coder** | implement, write code, pull request, refactor | напиш, код, создай, баг, тест |
| **Researcher** | search, find, what is, explain | найд, поищ, ищи, гугл |
| **Memory** | remember, save, note, obsidian, remind | запомн, сохран, заметк, напомн |

---

## Security

- Unknown tools → fail closed (`GateDecision.REJECT`)
- Dangerous tools → user confirmation required, bound to exact call signature
- The model cannot self-approve — code decides
- Shell-like `fol_command` → always requires confirmation
- Secrets never reach memory/logs/dashboard; API keys not committed (`.gitignore`)

---

## License

MIT — see [LICENSE](LICENSE).
