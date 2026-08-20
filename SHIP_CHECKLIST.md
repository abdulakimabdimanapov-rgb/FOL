# FOL — Ship Checklist (Stardance: Frictionless)

Status key: ✅ done / ⬜ not done / 🚫 blocked

## Mission & requirements

- [x] Frictionless mission selected
- [x] Clear quality-of-life problem defined (repetitive actions, repeated
      context explanation, app-switching friction)
- [x] Three major QoL improvements implemented:
      1. Desktop automation
      2. Context + persistent memory
      3. Proactive assistance
- [ ] >= 3 real hours tracked for FOL (see "Hackatime" section — WakaTime
      heartbeats are real and show project `SecondSelf`, but total tracked
      hours are controlled by the user's own tracking setup, not by this
      session)

## Working project

- [x] Repo imports and runs (P0 layout merge done — was completely broken)
- [x] All services start: Orchestrator :8420, Agent Server :8421, FOL API :8754
- [x] E2E check 14/14: `python3 scripts/e2e_check.py`
- [x] Root tests: 1168 passed / 4 skipped
- [x] FOL core tests: 810 passed
- [x] Orchestrator-local tests: 71 passed
- [x] macOS app builds: `cd fol-app && swift build`
- [x] Distributable artifact: `./build-app.sh` → `build/FOL.app` (ad-hoc signed)

## Security

- [x] Unknown tools fail closed (gate REJECT)
- [x] Dangerous tools require confirmation, bound to exact arguments
- [x] Model cannot self-approve (code decides, never the model)
- [x] Shell-like fol_command always gated
- [x] Secrets never enter memory/logs/dashboard (scrub tests pass)
- [x] `.env` / `.env.bak` ignored by git; templates committed with empty keys
- [x] Repo-wide secret scan clean (only test fixtures match patterns)

## Repository

- [x] Public source repository configured (remote: `SecondSelf.git`)
- [x] README — ship-ready, explains FOL in <2 min
- [x] Installation instructions in README + RELEASE_NOTES
- [x] Architecture overview in README + docs/
- [ ] Screenshots — ⬜ not yet captured (needs the app launched with a live
      LLM; demo harness exists: `./scripts/demo.sh`)
- [x] Demo instructions (`scripts/demo.sh`, `scripts/verify_scenarios.sh`)
- [x] License (MIT)
- [x] .gitignore
- [x] No secrets in tracked files
- [x] CI workflows present (pytest + syntax + Swift build)

## Stardance page

- [x] STARDANCE.md — project description (what / problem / solution / 3 QoL)
- [x] DEVLOG-2.md — devlog draft based on real completed work
- [x] No unsupported capabilities claimed

## Release prep

- [ ] Version: v1.0.0 (VERSION file) — could bump to v1.0.1 for this release
- [x] CHANGELOG.md exists (needs a v1.0.1 entry for this session's fixes)
- [x] README updated
- [ ] GitHub release notes — draft from DEVLOG-2 + this checklist
- [ ] Final devlog published on Stardance (draft ready: DEVLOG-2.md)

## Blocker status after pre-ship verification (2026-08-16)

1. **Live LLM demo — RESOLVED (via Ollama, no credits).** Ollama is
   installed and running locally with `llama3.2:3b`. Verified live:
   - LLM fallback chain works: OpenRouter (402) → Ollama, real response
   - FOL API `/api/chat` returned a real answer through the local model
   - Orchestrator `/command` ran a full agent loop → clean response, 0 tracebacks
   - ConfirmationGate live check: safe → `ok`, shell → `confirm`, unknown → `reject`
2. **Screenshots** — plan ready (`SCREENSHOTS.md`), captures pending (need
   the user to run the app with Ollama; real states only).
3. **First commit** — repo has no commits yet; everything untracked.
   Committing/pushing requires explicit user approval (per instructions).
4. **Hackatime project identity — RESOLVED.** Root cause: git remote is
   named `SecondSelf.git`, so WakaTime/Hackatime detected `SecondSelf`.
   Fix: `.wakatime-project` file (content `FOL`) created in repo root —
   official WakaTime mechanism, confirmed by CLI verbose log
   (`wakatime project file found at …/.wakatime-project`). Future real
   activity in this repo will be tracked as **FOL**. No history rewritten,
   no heartbeats fabricated, no unrelated projects touched.
5. **Hackatime hours** — 3-hour total must come from real tracked work on
   your Hackatime dashboard; this session cannot fabricate time.
