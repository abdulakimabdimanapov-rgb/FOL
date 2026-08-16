# FOL — Unified Core Architecture (Phase 2)

> Status: **Phase 2 — unified architectural foundation in place.**
> This document defines the canonical architecture, the responsibilities of
> each layer, the explicit request flow, and the legacy boundaries that are
> intentionally preserved.

---

## 1. Canonical components

The canonical FOL core lives in **`fol/`**. Everything else in the repository
is either an active execution layer (`orchestrator/`) or a legacy system to be
migrated later (see §6).

| Component | Canonical location | Responsibility |
|---|---|---|
| **LLM** | `fol/modules/llm/` | One routing abstraction for local/cloud/fallback models (`router.py`), native backends (`backends/`), engine (`engine.py`), personality/prompts |
| **Memory** | `fol/modules/memory/` | Stores (RAG, vector, episodic, long-term, Obsidian) behind a clean `MemoryService` boundary (`interface.py`) |
| **Tools** | `fol/modules/tools/` | Single canonical registry (`registry.py`) + metadata contract (`base.py` → `ToolSpec`) |
| **Input** | `fol/modules/input/` | Text, speech, vision, screen capture |
| **Output** | `fol/modules/output/` | TTS, Telegram, notifications, display — the canonical output boundary |
| **Plugins** | `fol/modules/plugins/` | Pluggable extension hooks |
| **Core lifecycle** | `fol/core/` | App bootstrap (`app.py`), explicit execution pipeline (`pipeline.py`), orchestrator (`orchestrator.py`), event bus, tasks, context |
| **API** | `fol/api/` | REST + WebSocket servers (port 8754) |

No functionality is duplicated across subsystems: the orchestrator keeps only
what belongs in the active execution layer, and everything new goes through
the canonical interfaces above.

---

## 2. Responsibilities

### 2.1 FOL core (`fol/core`)
- Owns the **explicit request flow** — the `ExecutionPipeline`
  (`core/pipeline.py`) with stages
  `INTENT → CONTEXT → MEMORY RETRIEVAL → PLAN → TOOL/AGENT SELECTION →
  EXECUTION → VERIFICATION → RESPONSE → MEMORY UPDATE`.
- `core/orchestrator.py` binds the live stage handlers and is the deterministic
  driver; the last run is observable via `orchestrator.last_pipeline`.
- `core/app.py` (`FOL` class) is the application root: it wires modules,
  handles built-in commands, screen awareness, and the personality layer.

### 2.2 Orchestrator (`orchestrator/`)
- The **active execution layer** used by the macOS UI / bridge today.
- Responsible for: agent routing (`agents/router.py`), the streaming chat
  endpoint, tool-call streaming, the loop guard, and desktop execution via
  `agent-server/`.
- It talks to the FOL core through the FOL API (port 8754, `fol_command`).
- **Kept as-is this phase.** Its LLM calls still go through the legacy
  `analyze/_llm*.py` adapter (see §5, §6).

### 2.3 LLM (`fol/modules/llm/`)
- **`router.py` — the single routing abstraction.** New code uses the
  `LLMRouter` interface (`complete_sync` / `acomplete` / `astream` /
  `model_chain` / `available_providers` / `test_connection`), obtained via
  `get_llm_router()`.
  - `LiteLLMRouter` — local (`ollama/…`, `local/…`) + cloud (OpenAI,
    Anthropic, Gemini, OpenRouter, …) + **fallback chain**
    (`LLM_MODEL` + `LLM_FALLBACK_MODELS`, providers without a key are skipped).
  - `EngineBackendRouter` — adapter over the native `LLMEngine` (MLX /
    OpenAI / Anthropic / OpenRouter backends).
  - API keys are read **only** from the environment / `.env` — never
    hardcoded, never logged.
- Registered on the app as the `llm_router` module.

### 2.4 Memory (`fol/modules/memory/`)
- **`interface.py` — the orchestrator↔memory boundary**: `retrieve_context`,
  `store_memory`, `retrieve_relevant_memories`, `record_episode`.
- `RAGMemoryService` is the reference adapter over the existing stores
  (RAG pipeline, vector store, episodic memory, long-term memory) with
  graceful fallback between stores.
- Registered on the app as the `memory_service` module.
- **No store was migrated or deleted this phase.**

### 2.5 Tools (`fol/modules/tools/`)
- **`ToolRegistry` is the canonical registry.** Every tool is described by a
  `ToolSpec`:

  | Field | Meaning |
  |---|---|
  | `name` | unique tool id |
  | `description` | natural-language description for the LLM |
  | `schema` | JSON-schema style parameters |
  | `risk_level` | `low` / `medium` / `high` / `critical` |
  | `requires_confirmation` | must the user approve execution? |
  | `execution` | the executable `AbstractTool` |

- `registry.requires_confirmation(name)` / `high_risk_tools()` / `to_anthropic_tools()`
  give the execution layer a deterministic confirmation gate.
- High-risk tools (`execute_command`, desktop input, email, calendar) are
  annotated `high` + confirmation-required.

---

## 3. Request execution flow (explicit)

```
USER REQUEST
    ↓
INTENT             is it a follow-up? what kind of task?     [core.orchestrator]
    ↓
CONTEXT            conversation history + session metadata   [context_manager]
    ↓
MEMORY RETRIEVAL   RAG / long-term context for the prompt    [rag → memory boundary]
    ↓
PLAN               chain-of-thought prompt for complex tasks [THINKING_PROMPT]
    ↓
TOOL / AGENT SELECTION   tool routing (app layer today)      [skipped in core when unwired]
    ↓
EXECUTION          run the chosen tools                      [app layer: FOL.process]
    ↓
VERIFICATION       deterministic gate (plan executable?)     [core.orchestrator]
    ↓
RESPONSE           LLM generation + quality fallback         [llm router]
    ↓
MEMORY UPDATE      store the turn / episodes                 [context_manager + rag]
```

Two live paths both implement this flow:

1. **Core path** — `core.orchestrator.Orchestrator.process_input` runs the
   explicit `ExecutionPipeline` (all stages above; tool stages are skipped in
   the core because the app layer owns tools). This is the canonical,
   deterministic, tested driver.
2. **App path** — `core.app.FOL.process` implements the same stages at the
   application level (screen awareness → builtin commands → tools → LLM →
   personality-layer verification → memory) and is what the REST API serves.

---

## 4. Import layout & sys.path

- `fol/` is a **flat import root** (not a package): `fol/` is inserted on
  `sys.path`, then `core.*`, `modules.*`, `config.*`, `api.*` are imported.
  This is the established pattern (`fol/main.py`, `fol/run_api_server.py`).
- Root-level modules (`analyze/`, `orchestrator/`, `utils/`, `obsidian/`,
  `src/`) live in the **root import world** and do not import `fol/`.
- The two worlds are bridged only at documented seams (FOL API on 8754, the
  legacy `analyze/` adapter). New code should not add new `sys.path` hacks.

---

## 5. Legacy boundaries (preserved, not deleted)

| Legacy system | Role today | Phase 2 status |
|---|---|---|
| `analyze/_llm.py`, `_llm_async.py` | LiteLLM model-chain used by `orchestrator/`, `obsidian/`, `src/` | **Legacy LLM adapter.** Superseded by `modules/llm/router.py` (`LiteLLMRouter`); kept intact — its ~100 tests still pass. Migration = point the orchestrator at `get_llm_router()`. |
| `orchestrator/` tool dicts (`BROWSER_TOOLS`, `DESKTOP_TOOLS`, …) | Active tool catalog for the streaming agent | **Legacy tool registry.** Canonical replacement = `fol/modules/tools/` (`ToolSpec`). Kept for compatibility. |
| `src/` (legacy Second Self web) | Old FastAPI + Next.js app | Preserved; do not build new features here. |
| `agent-server/` | Desktop execution server (port 8421) | Active execution backend for the orchestrator. |
| `bridge/`, `dashboard/`, `SecondSelf/` | Mobile bridge, monitoring, macOS app | Preserved; `SecondSelf/` must not be renamed in this phase. |
| `utils/episodic_writer.py` | Standalone episodic writer | Preserved; migration target = `modules/memory/episodic_memory.py`/`interface.record_episode`. |

Rules: do not delete legacy systems, do not depend on them from new code,
and mark legacy paths in new documentation.

---

## 6. Migration map (remaining work)

1. **Orchestrator → canonical LLM router.** Swap `orchestrator/server.py`'s
   `analyze._llm_async` imports for `LiteLLMRouter` (same event contract),
   then remove the legacy `analyze/` adapter.
2. **Orchestrator → canonical tool registry.** Replace the `orchestrator/`
   tool dicts with `ToolRegistry` + `ToolSpec` (risk/confirmation gating).
3. **Memory migration.** Move `RAGMemoryService` into the live app path and
   retire duplicate stores; wire `record_episode` into daily flows.
4. **Brain optimization** (ROADMAP) — deferred by design.
5. **`SecondSelf/` → FOL rename** — deferred by design.

---

## 7. Testing

```bash
cd fol && python3 -m pytest tests/ -q      # FOL core (810)
python3 -m pytest tests/ -q                # root suite incl. legacy adapters (1168)
bash scripts/verify_scenarios.sh           # live end-to-end scenarios
```

New regression suites: `fol/tests/modules/llm/test_router.py`,
`fol/tests/modules/tools/test_tool_spec.py`, `fol/tests/core/test_pipeline.py`,
`fol/tests/modules/memory/test_memory_interface.py`,
`fol/tests/modules/output/test_output_channels.py`.
