# FOL: Turning a Chatbot into a Computer Assistant

**Devlog #2** — actual work, accumulated across the project (the repo had no
commits when this session started; everything below is real, verified work
in the current tree).

---

## What changed since the previous devlog

The project started as two separate halves: a Python backend (`Fol/`) and a
SwiftUI app + FOL core (`SecondSelf/`). The documentation (`MERGED_README.md`)
described a single merged project, but the filesystem still held two unmerged
trees — and because of that, **the project did not run at all**: imports failed
(`No module named 'modules'`), every orchestrator test errored, and
`run_all.sh` could not find `fol/run_api_server.py`.

**The main work of this session was making the project actually work, then
proving it.**






## ToolRegistry

A single canonical registry for all 50 tools now lives in
`fol/modules/tools/registry.py`. Every tool is defined exactly once
(`ToolSpec`: name, description, schema, risk level, confirmation
requirement). The orchestrator derives its legacy tool catalogs from it —
one source of truth, no duplicated schemas.

## LLM Router

`llm_bridge` routes through a canonical LiteLLM router with an automatic
fallback chain (`LLM_MODEL` → `LLM_FALLBACK_MODELS`), skipping models whose
API key isn't configured. The chain is logged at startup:
`Model chain: ... -> ...`. Two-stage tool selection (classify → 5-12 tools)
keeps small models reliable.

## MemoryService

Memory is layered: identity / preferences / episodic files + Obsidian vault
+ daily tracker, injected into every LLM request (`build_context_messages`,
`build_system_prompt`). Verified live: memory tools (`save_to_obsidian`,
`get_daily_summary`) are registered and tested.

## ConfirmationGate

`fol/modules/tools/gate.py` is the single, code-enforced safety gate. The
model can never decide — the gate decides from registry metadata + rules:
- Unknown tool → REJECT (fail closed)
- High-risk / shell-like tool → CONFIRM, bound to the exact call signature
  (changing one argument invalidates an approval)
- Model cannot self-approve

Security regression tests (`tests/test_safety_audit.py`) pass.

## Proactive Mode

Three triggers in `orchestrator/suggestion_engine.py`: profile-based,
pattern-based, and ambient (30s loop with desktop screenshot). Suggestions
broadcast over the persistent `/events` SSE channel and render as in-UI
banners in the SwiftUI app (`SuggestionBanner.swift`). FOL core has an
explicit `proactive on/off` toggle. The ambient loop is wired into the
orchestrator lifespan.

## Real bugs found and fixed

1. **Repo layout (P0)** — merged `Fol/` + `SecondSelf/` into the single
   root the docs and code always expected. Before: 0 tests could import.
   After: 1168 root tests pass.
2. **`fol_command` handler binding (P0)** — the handler context captured
   `call_fol_api` by reference at import, so `patch("server.call_fol_api")`
   never took effect; the handler silently called the real (offline) FOL
   server. Now resolved through the module global at call time.
3. **Empty FOL command** — the documented "Empty command" error was
   unreachable: schema validation rejected empty/missing `command` before
   the handler could return its friendly message. Fixed.
4. **E2E false positive** — the log check flagged `litellm.APIError`
   (provider-fallback notices, the designed graceful-degradation path) as
   "ERROR" because it greps the substring. Now it flags real tracebacks and
   log-level ERROR records only.
5. **Swift build broken by stale module cache** — the `.build` directory
   was carried over from the pre-merge path; `swift build` failed on
   `SwiftShims` precompiled cache. Clean rebuild fixes it.
6. **`build-app.sh` signing** — macOS "resource fork, Finder information, or
   similar detritus not allowed"; added `xattr -cr` before codesign so the
   `.app` bundle builds and signs in one command.
7. **Secrets hygiene** — `.env.bak` / `.env.template` contained real API
   keys but were NOT in `.gitignore` (only `.env` was). Templates are now
   committed (empty keys), real config stays ignored. A repo-wide secret
   scan is clean.

## Real testing

- `python3 -m pytest tests/` → **1168 passed, 4 skipped**
- `python3 -m pytest fol/tests/` → **810 passed**
- Orchestrator-local tests → **71 passed**
- `python3 scripts/e2e_check.py` → **14/14** (services start, health OK,
  MJPEG frames, SSE chat with tokens + complete state, no tool-call leaks,
  no tracebacks in logs)
- `cd SecondSelf && swift build` → **clean**
- `./build-app.sh` → **build/Second Self.app** (ad-hoc signed)

## What I learned

- **Layout is a feature.** Two trees that "describe the same merge" but
  don't match on disk means zero tests run. The docs were right; the
  filesystem lied. Aligning the tree to the documented architecture was the
  single highest-leverage fix.
- **Bind collaborators lazily.** A context that captures functions at import
  time is untestable and silently wrong when the live dependency is down.
  Resolve through module globals at call time.
- **The confirmation gate is the product.** Making the model unable to
  self-approve and binding approvals to exact arguments is what makes
  "assistant controls my Mac" safe enough to ship.
- **Graceful degradation is a feature to test for.** Provider fallback
  produced user-visible, humanized errors even with zero credits — and the
  test suite must distinguish that from real failures.

---

*Next: live voice test, browser cookie sync, Google OAuth flows, demo
video, and the v1.0.1 release notes.*
