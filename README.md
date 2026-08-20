# FOL — Personal AI Assistant (JARVIS for macOS)

> **Status: v1.0.0** — stable release, 989+ tests, 5 real-world daily-use scenarios working end-to-end.

**One unified project** — FOL: Python AI core + native SwiftUI macOS application.

## What is FOL?

FOL is a **digital twin** and personal AI assistant that:

* 🖥️ Lives on your **MacBook** inside the notch with a native Notch UI
* 🧠 Provides **JARVIS-like capabilities** including voice, vision, memory, and tools
* 🔄 Understands **context** from your screen, email, calendar, and active applications
* 📝 Writes to **live memory** using Obsidian + episodic memory
* 🤖 Uses an **agentic loop** to select tools, execute actions, verify results, and respond

## Working End-to-End Scenarios

| Scenario                                           | How it works                                                 |
| -------------------------------------------------- | ------------------------------------------------------------ |
| “Open Safari and find the latest OpenAI news”      | Opens Safari → searches → returns a summary                  |
| “Write an email to my teacher”                     | Asks for the contact or uses Google OAuth                    |
| “Create a calendar event”                          | Uses `create_event` through Google Calendar                  |
| “Open the FOL project”                             | Uses Finder + keyboard automation                            |
| “Remember that I need to send the report tomorrow” | Saves the information using `save_to_obsidian` → live memory |

## Quick Start

```bash
# 1. Configure your LLM in .env (see the "LLM" section below)
cp .env.example .env   # or edit your existing .env

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start all services
./run_all.sh

# 4. Or start services individually:
./run_all.sh orchestrator   # AI server (port 8420)
./run_all.sh agent          # Desktop control (port 8421)
./run_all.sh fol            # FOL API with JARVIS commands (port 8754)
./run_all.sh swift          # SwiftUI macOS application
```

## LLM Configuration

Everything runs through **LiteLLM**, so changing the model only requires changing one line:

```env
# Free (OpenRouter free models, 120B — excellent for tool calling)
LLM_MODEL=openrouter/nvidia/nemotron-3-super-120b-a12b:free
OPENROUTER_API_KEY=sk-or-v1-...

# Or locally (Ollama) — no API required, but weaker for 50+ tools
LLM_MODEL=ollama/llama3.2:3b

# Or paid (after adding credits)
LLM_MODEL=openai/gpt-4o-mini
OPENAI_API_KEY=sk-proj-...

# Maximum response tokens (depends on provider balance/limits)
LLM_MAX_TOKENS=1500

# Fallback: if the primary model is unavailable,
# try these models in order
LLM_FALLBACK_MODELS=ollama/llama3.2:3b
```

### Automatic Model Failover

If the primary model becomes unavailable due to a free-tier limit, provider outage, API error, or other failure, FOL automatically tries the models listed in `LLM_FALLBACK_MODELS` in order.

Models without a configured API key are automatically skipped.

This allows the system to keep working as long as at least one model is available.

The model chain is logged during startup:

```text
Model chain: primary -> fallback -> ...
```

### Two-Stage Tool Selection

One of FOL's key architectural advantages is its **two-stage tool selection system**.

The LLM never receives all 50+ tools at once.

Instead:

```text
User request
     ↓
Category classification
     ↓
Email / Calendar / Memory / Web / Coding / Desktop
     ↓
5–12 relevant tools
     ↓
LLM tool selection
     ↓
Tool execution
```

This significantly reduces tool-selection complexity.

Even smaller models such as 3B models can select tools reliably, while larger models such as 120B models provide much stronger reasoning and tool-calling performance.

## Architecture

```text
User (Notch UI / Web / Voice)
          │
          ▼
Orchestrator (FastAPI, :8420)
          │
          │ Agent Router
          │ General / Architect / Coder / Reviewer /
          │ Researcher / Memory
          │
          │ Two-stage tool selection
          │ Category → 5–12 relevant tools
          │
          │ Loop Guard
          ▼
LLM (LiteLLM: OpenRouter / Ollama / OpenAI)
          │
          │ Tool Calls
          ▼
Execution Layer
    │
    ├── Agent Server (:8421)
    ├── Productivity (Gmail / Calendar)
    ├── Obsidian
    └── FOL API (:8754)
          │
          ▼
Tool Result → LLM
          │
          ▼
Final Response
          │
          ▼
SSE Streaming → UI
```

## Project Structure

```text
SecondSelf/
├── SecondSelf/              # SwiftUI macOS app (Notch UI, voice, animations)
├── orchestrator/            # FastAPI AI server (:8420)
│   ├── agents/              # General/Architect/Coder/Reviewer/Researcher/Memory + router
│   └── productivity_tools.py# Gmail, Calendar, Docs, web search
├── agent-server/            # Desktop/browser control (:8421)
├── fol/                     # Python AI core / FOL API (:8754)
├── src/                     # Next.js web interface (SSE chat)
├── auth/                    # Google OAuth (Gmail/Calendar)
├── fetch/                   # Gmail, Tavily, Calendar fetchers
├── analyze/                 # LLM layer and analysis (voice, behavior, topics)
├── obsidian/                # Live memory (vault, linker, tools)
├── context_engine/          # Screen context (active app, URL)
├── utils/                   # episodic_writer, daily_tracker, text_normalizer
├── cookie_sync/             # Chrome cookie synchronization
├── tests/                   # 989+ tests
├── scripts/
│   ├── verify_scenarios.sh  # Automated verification of 5 scenarios
│   └── demo.sh              # Demo recording harness
├── Dockerfile / docker-compose.yml / .github/workflows/
└── run_all.sh               # Unified launcher
```

## Demo

Use the following script to run the complete demo:

```bash
./scripts/demo.sh
```

For shorter pauses:

```bash
DEMO_PAUSE=5 ./scripts/demo.sh
```

For a quick verification without pauses:

```bash
DEMO_QUICK=1 ./scripts/demo.sh
```

### Demo Scenarios

1. **“Open Safari”**
2. **“Find the latest OpenAI news”**
3. **“Remember I need to send the report tomorrow”**
4. **“Open the FOL project”**
5. **“Create a calendar event”**

## Quality & Reliability

* **989+ tests** using `python3 -m pytest tests/ -v`
* Router and agent tests
* Text normalization
* Memory system
* Tool execution
* SSE streaming
* Loop guard
* Model fallback system
* Response formatter
* End-to-end scenario verification

### Loop Guard

The agent cannot get stuck in an infinite tool-execution loop.

If the same tool is repeatedly called beyond the configured limit, the loop guard interrupts execution while preserving a valid conversation history.

### Memory

FOL maintains multiple layers of persistent memory:

```text
identity.md
preferences.md
episodic.md
      │
      ├── Obsidian
      └── Daily Tracker
```

This allows FOL to maintain context across conversations and sessions.

### CI

GitHub Actions automatically runs:

* Python test suite
* Swift build
* Integration checks

on every push.

## Ports

|  Port | Service      | Description                  |
| ----: | ------------ | ---------------------------- |
|  8420 | Orchestrator | Main AI server / SSE `/chat` |
|  8421 | Agent Server | Desktop and browser control  |
|  8754 | FOL API      | JARVIS commands              |
|  3000 | Next.js      | Web interface                |
| 11434 | Ollama       | Optional local LLM           |

## Documentation

* **`CHANGELOG.md`** — version history, currently **v1.0.0**
* **`MERGED_README.md`** — complete documentation about the project merge
* **`FOL_UPGRADE.md`** — master architecture document
* **`CLAUDE.md`** — AI model context and development instructions
* **`DESIGN.md`** — design system

## Project Vision

FOL is designed to become more than a chatbot.

The goal is a **persistent AI companion for macOS** that can understand context, remember information, interact with applications, use tools, and act on the user's behalf while keeping the user in control.

```text
SEE
 ↓
UNDERSTAND
 ↓
PLAN
 ↓
ACT
 ↓
VERIFY
 ↓
REMEMBER
```

**FOL is the AI layer between you and your Mac.**
