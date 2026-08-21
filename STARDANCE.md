# FOL — Stardance Project Page

## What

**FOL** (Friendly Obedient Listener) is a personal AI assistant for macOS —
a "digital twin" living in the MacBook notch. It is built as a Python AI core
(FastAPI + LiteLLM) driving a SwiftUI Notch UI, with browser/desktop
automation, persistent memory, and proactive suggestions.

## Problem

Everyday computer work creates friction:

1. **Repetitive actions** — the same clicks, searches, and file operations
   are done over and over.
2. **Repeated context explanation** — the assistant forgets who you are and
   what you're working on.
3. **App-switching overhead** — jumping between browser, mail, calendar,
   files, and terminal.

## Solution

FOL reduces this friction with three quality-of-life improvements:

### 1. Desktop automation
Stop repeating routine macOS actions. FOL opens apps, drives the browser
(Chrome + Safari), types, clicks, screenshots, and runs JARVIS-style
commands ("open Safari and find the latest OpenAI news") — with a
deterministic confirmation gate before any dangerous action.

### 2. Context + persistent memory
FOL remembers context and preferences. Identity, preferences, episodic
history and daily notes are injected into every request, stored in an
Obsidian vault + local files — so you never explain the same thing twice
("remember I need to send the report tomorrow" → next session it knows).

### 3. Proactive assistance
FOL notices useful context and offers an action instead of waiting for a
command: pattern detection after jobs, ambient desktop analysis every 30s,
profile-based suggestions — all delivered as in-UI suggestion banners with
an explicit on/off toggle so it never becomes nagging.

## Facts

- **Location:** macOS desktop app (Notch UI) + web chat (Next.js)
- **Stack:** Python 3.9+ (FastAPI, LiteLLM, PyAutoGUI, AppleScript),
  SwiftUI, Next.js, Obsidian
- **Models:** any LiteLLM provider with automatic fallback chain
  (OpenRouter / Ollama local / OpenAI)
- **Ports:** 8420 Orchestrator · 8421 Agent Server · 8754 FOL API · 3000 Web
- **Tests:** 2049+ passing (1168 root + 810 FOL core + 71 orchestrator),
  E2E 14/14, Swift build clean
- **License:** MIT
