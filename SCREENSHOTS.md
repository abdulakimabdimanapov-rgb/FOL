# FOL — Screenshot Plan (Stardance)

Six screenshots needed. All must capture **real working states** — do not
compose or fake them. Prereq: an API key for an LLM provider (OpenRouter /
OpenAI / Anthropic) in `.env` — FOL uses cloud-only brains (no local LLMs).

## Setup for every shot

```bash
cd ~/Desktop/Fol
./run_all.sh            # starts orchestrator :8420, agent :8421, fol :8754
```

## 1. FOL Notch UI

- Launch: `cd fol-app && swift run` (or `open "build/FOL.app"`)
- Capture the Notch panel with the chat input visible.
- **Tool:** macOS `Cmd+Shift+4` region capture → `screenshots/01-notch-ui.png`

## 2. FOL main interaction

- Type in the notch (or `curl`): `What is the current time?`
- Wait for the streamed answer (streamed from the API provider).
- Capture the response bubble.
- **Tool:** region capture → `screenshots/02-interaction.png`

## 3. Tool confirmation

- Ask FOL to do something gated, e.g. `send an email to a@b.c` — the
  ConfirmAction card appears before execution (ConfirmationGate).
- Capture the approval card with Allow/Deny.
- **Tool:** region capture → `screenshots/03-confirmation.png`

## 4. Memory / context

- Ask: `remember that I am working on the FOL project`
- Then in a fresh message: `what project am I working on?`
- Capture the second answer showing it remembers.
- **Tool:** region capture → `screenshots/04-memory.png`

## 5. Proactive suggestion

- Proactive mode is off by default (not annoying). Enable it:
  `curl -X POST http://localhost:8754/proactive/toggle -H 'Content-Type: application/json' -d '{"enabled":true}'`
- Wait up to ~30s for the ambient loop, or trigger via pattern detection
  after a few related requests.
- Capture the SuggestionBanner with Accept/Dismiss.
- **Tool:** region capture → `screenshots/05-proactive.png`

## 6. Architecture / test result (text-based)

- Terminal: `python3 scripts/e2e_check.py` → expect **14 passed, 0 failed**
- Capture the summary output.
- **Tool:** `Cmd+Shift+4` full window → `screenshots/06-tests.png`

## Verification

- All 6 files in `screenshots/` (or a `docs/screenshots/` folder).
- Each file must come from a real running FOL — no mockups.
- Optional: `ffmpeg -f avfoundation` screen-recording for a short demo GIF.
