# INTERNAL MIGRATION MAP — FOL + fol-app + Freebuff + Obsidian

> **Phase 1 audit result.** Nothing was deleted or changed — this document
> only records what exists, where it lives, and what must move for the
> unified architecture:
>
>     ONE ORCHESTRATOR · ONE BRAIN INTERFACE · ONE MEMORY INTERFACE · ONE SECURITY GATE
>     Freebuff = primary brain (future) · LiteLLM = fallback · Obsidian = persistent memory
>     fol-app = source of migrated capabilities, NOT a separate brain.
>
> Status: **audit complete. No code changed.**

---

## 1. Capability matrix (what exists where)

Legend: **FOL** = `fol/` (canonical core), **SS** = `fol-app/` (SwiftUI app),
**ORCH** = `orchestrator/` (active execution layer), **ROOT** = root-level modules
(`obsidian/`, `context_engine/`, `analyze/`, `src/`, `agent-server/`).

| # | Capability | FOL (`fol/`) | fol-app (`fol-app/`) | Other layers | Duplicated? | Status |
|---|---|---|---|---|---|---|
| 1 | LLM routing | `modules/llm/router.py` (`LiteLLMRouter`), `engine.py`, `backends/` | — | `analyze/_llm*.py` (legacy resilience), `orchestrator/llm_bridge.py` | No (bridge delegates to FOL) | ✅ FOL canonical |
| 2 | Brain abstraction | `modules/llm/brain.py`: `BrainInterface`, `CurrentLLMAdapter`, `FreebuffBrainAdapter` (disabled) | — | `orchestrator/llm_bridge.py` → `get_brain("current")`; `suggestion_engine.py` → `get_brain("current")` | No | ✅ ONE BrainInterface |
| 3 | Orchestrator | `core/orchestrator.py`, `core/pipeline.py` (canonical pipeline) | — | `orchestrator/server.py` (active execution layer: `/chat` SSE, tool-call loop, agents) | ⚠️ TWO orchestrators | **MIGRATE target**: execution layer should sit on FOL core pipeline |
| 4 | Tool registry | `modules/tools/registry.py`, `base.py` (`ToolSpec`) | — | `orchestrator/tool_registry.py`, `tool_handlers.py`, `productivity_tools.py` (legacy dicts) | ⚠️ two registries | **MIGRATE target** |
| 5 | Security gate | `modules/tools/gate.py` (`ConfirmationGate`) | `Views/ConfirmActionView.swift`, `TaskApprovalView.swift` (UI only) | `orchestrator` gate logic | UI in SS only | ✅ gate canonical in FOL; SS renders |
| 6 | Voice input (record + STT) | `modules/input/speech.py` (`VoiceAssistant`, sounddevice+Google), `speech_recognizer.py` (mlx-whisper), API `/api/stt` | `Services/AudioRecorder.swift` (AVAudioRecorder), `SpeechService.swift` (Whisper cloud), `ElevenLabsService.swift` (Scribe cloud), `LocalSTTService.swift` (→ FOL `/api/stt`) | — | ✅ DUPLICATED | **Partially migrated**: mic works via FOL local STT; SS cloud STT still parallel |
| 7 | TTS | `modules/output/tts.py` (macOS `say`), `TTSModule` | `Services/ElevenLabsService.swift` (JARVIS voice, cloud) | — | ✅ DUPLICATED (different providers) | **MIGRATE target**: unify under FOL output |
| 8 | Screen awareness | `modules/input/screen_capture.py`, `vision.py` (screenshot→OCR/vision), `core/app.py` `_take_screenshot` | — (renders PeepingView/VNCPip) | `context_engine/` (ROOT: `snapshot.py`, `browser_url.py`, `app_monitor.py`) used by orchestrator | ⚠️ two paths | **MIGRATE target**: unify context under FOL |
| 9 | Browser | `modules/tools/browser/` (`browser_automation.py`, `browser_interact.py`, `web_scraper.py`, `bookmarks.py`) | — | `agent-server/` (port 8421) browser endpoints; `orchestrator` `BROWSER_TOOLS` dicts | ⚠️ FOL + agent-server | FOL owns engine; agent-server executes |
| 10 | Memory stores | `modules/memory/`: `rag.py`, `vector_store.py`, `episodic_memory.py`, `long_term.py`, `sql_store.py`, `knowledge_graph.py`, `conversation.py`, `preferences.py`, `identity/`, `obsidian.py`, `brain.py` | — | `utils/episodic_writer.py` (ROOT, local `episodic.md` mirror) | ⚠️ several stores | **MIGRATE target**: one `MemoryInterface`, Obsidian canonical |
| 11 | Memory interface | `modules/memory/interface.py` (`MemoryService` / `RAGMemoryService`) + API `/api/memory/*` | — | `orchestrator/memory_bridge.py` → FOL API (single path, secret-filtered) | No | ✅ ONE memory boundary |
| 12 | Obsidian integration | `modules/memory/obsidian.py` (`ObsidianMemory`), `modules/memory/brain.py` (`Brain` — "Freebuff Brain" markdown memory), API `/api/obsidian/save` | — | `obsidian/` (ROOT REST package: `client.py`, `vault.py`, `daily.py`, `linker.py`, `sync.py`, `tools.py`, `config.py`) used by orchestrator | No | ✅ memory layer |
| 13 | Proactive assistance | `modules/llm/proactive.py` (`ProactiveService`) + API `/api/proactive/*` | `Models/ProactiveSuggestion.swift`, `Views/SuggestionBanner.swift`, SSE `/events` handling in `ChatViewModel` | `orchestrator/suggestion_engine.py` (SSE `/events` suggestion source) | ✅ **DUPLICATED (two proactive engines)** | **MIGRATE target** |
| 14 | Agents | — | — | `orchestrator/agents/` (`router.py`, `coder.py`, `architect.py`, `reviewer.py`, `researcher.py`, `memory.py`) | No | ORCH only |
| 15 | UI (Notch, chat, confirm, voice button) | — | `Views/*`, `NotchOverlayController.swift`, `NotchPanel.swift`, `VoiceInputButton.swift` | — | SS only (macOS UI) | stays as **the FOL UI** |
| 16 | Profile / synthesis | — | — | `src/synthesis/profile.py`, `analyze/*` (ROOT legacy) | — | legacy; uses bridge → BrainInterface |
| 17 | Voice UI + state | — | `Views/VoiceInputButton.swift`, `Models/VoiceInputState.swift` | — | SS only | stays UI |
| 18 | Desktop execution | `modules/tools/desktop/agent_tools.py`, `modules/tools/automation/`, `mouse_keyboard/` | — | `agent-server/` (port 8421) | ⚠️ FOL + agent-server | FOL owns tools; agent-server executes |
| 19 | Web tier | — | — | `src/` (Next.js + FastAPI) | — | legacy; keep |

---

## 2. What exists ONLY in FOL (canonical, keep)

- `modules/llm/` — router, engine, backends, personality, prompts, `brain.py` (BrainInterface), proactive, behavioral learner, memory enhancer.
- `modules/memory/` — all stores + `interface.py` + `obsidian.py` + `brain.py` (Obsidian memory).
- `modules/tools/` — registry, gate, system/desktop/browser/automation tools.
- `modules/input/` — speech, speech_recognizer, screen_capture, vision, text_input.
- `modules/output/` — tts, notifications, telegram, clipboard_out, display.
- `core/` — app, pipeline, orchestrator, context_manager, event_bus, task_manager, lifecycle.
- `api/` — REST (8754) + websocket; routes: conversation, memory, tools, proactive, plugins, settings; `/api/chat`, `/api/stt`, `/api/obsidian/save`, `/health`.

## 3. What exists ONLY in fol-app (macOS UI — REMAINS as the FOL UI)

- `NotchOverlayController.swift`, `NotchPanel.swift` — notch UI.
- `Views/*` — chat, confirm cards, suggestion banner, voice button, tool pills, VNC/peeping, setup wizard.
- `Services/AudioRecorder.swift` — AVAudioRecorder capture (the actual mic recording happens HERE; FOL has its own Python capture, unused by the app).
- `Models/` — ChatMessage, TwinState, VoiceInputState, ProactiveSuggestion, SSEParser.

## 4. What exists in BOTH (duplication — migration targets)

| Duplication | FOL side | fol-app / other side | Decision |
|---|---|---|---|
| **Voice STT** | `modules/input/speech.py` + `speech_recognizer.py` (mlx-whisper) + API `/api/stt` | `AudioRecorder` + `SpeechService` (Whisper cloud) + `ElevenLabs` (Scribe) + `LocalSTTService` (→ FOL) | MERGE: app should record (AudioRecorder — keep in UI) and transcribe via FOL `/api/stt` (done), cloud STT becomes optional provider inside FOL |
| **TTS** | `modules/output/tts.py` (macOS `say`) | `ElevenLabsService` (JARVIS cloud) | MERGE: ElevenLabs becomes a TTS provider behind FOL output; `say` = local fallback |
| **Proactive** | `modules/llm/proactive.py` + `/api/proactive/*` | `orchestrator/suggestion_engine.py` + SSE `/events` + SuggestionBanner UI | MERGE: ONE proactive engine (recommend: FOL ProactiveService, with suggestion_engine behavior ported), UI stays |
| **Screen/context** | `modules/input/screen_capture.py` + `vision.py` + core | `context_engine/` (ROOT: snapshot, browser_url, app_monitor) used by orchestrator | MERGE: context_engine functionality moves under FOL input; orchestrator consumes FOL |
| **Orchestrator** | `core/orchestrator.py` + `core/pipeline.py` | `orchestrator/server.py` (active layer: `/chat` SSE, agents, tool loop) | MERGE: server.py becomes thin transport over the FOL core pipeline (or documented compatibility) |
| **Tool registry** | `modules/tools/registry.py` | `orchestrator/tool_registry.py` + legacy dicts | MERGE: orchestrator consumes canonical registry (already partially: `orchestrator_tools.py` registers into it) |

## 5. fol-app → FOL: already migrated (evidence)

1. **Local STT**: `LocalSTTService.swift` → `POST {FOL}:8754/api/stt` (mlx-whisper) — mic works without cloud keys; graceful "mlx-whisper not installed" error surfaced. (`fol-app/Services/LocalSTTService.swift`)
2. **ServerConfig**: app points at FOL API :8754 (`/health`, `/api/stt`) alongside orchestrator :8420. (`fol-app/Utilities/DesignTokens.swift`)
3. **FOL as backend**: app launches `fol/run_api_server.py` in local mode — FOL REST API is a runtime dependency of the UI. (`fol-app/FOLApp.swift`)
4. **BrainInterface**: `orchestrator/llm_bridge.py` + `suggestion_engine.py` now call `get_brain("current")` — the orchestrator's LLM path sits on the ONE brain abstraction. (`orchestrator/llm_bridge.py`, `orchestrator/suggestion_engine.py`)
5. **Memory single path**: `orchestrator/memory_bridge.py` → FOL API `/api/memory/*` with deterministic secret filtering. (`orchestrator/memory_bridge.py`)

## 6. fol-app → FOL: NOT yet migrated

1. `AudioRecorder.swift` capture logic has no FOL counterpart used by the app (FOL Python mic capture exists but is not wired into the UI).
2. Cloud STT (`SpeechService`, `ElevenLabs STT`) still calls cloud APIs directly from the app — should become providers behind FOL `/api/stt`.
3. ElevenLabs TTS (JARVIS voice) is app-side only — FOL output has no ElevenLabs provider.
4. Proactive suggestions: app consumes orchestrator `/events` SSE from `suggestion_engine.py`, not the FOL `/api/proactive/*` engine — two sources.
5. The app's tool-confirmation cards render decisions from the orchestrator gate — the canonical gate is FOL's; transport must be verified to stay on one gate.

## 7. Where Obsidian is used (memory layer)

| Path | Role |
|---|---|
| `fol/modules/memory/obsidian.py` — `ObsidianMemory` | Vault folders People/Preferences/Knowledge/Conversations/Projects/Episodes; search/read/RAG context. Wired in `fol/core/app.py` (`self._obsidian`). |
| `fol/modules/memory/brain.py` — `Brain` ("Freebuff Brain") | `Brain/User.md`, `Preferences.md`, `Projects.md`, `Model-Log.md`, `Work-Log/YYYY-MM-DD.md`, `Daily-Summary/`, optional shared vault mirror (`Profile/`, `Goals/`, `Models/`, `Conversations/`). Wired in `fol/core/app.py` (`self._brain`). This is **memory**, not an LLM brain. |
| `obsidian/` (ROOT package) | REST client + vault/daily/linker/sync/tools — used by `orchestrator/server.py` (execute_memory_tool, ensure_daily_note, sync_to_obsidian, init_obsidian_vault, check_connection) and by `memory/brain.py` daily-note append. |
| `fol/api` `/api/obsidian/save`, `/api/memory/*` | REST surface the orchestrator/UI use; `orchestrator/memory_bridge.py` is the single secret-filtered path. |
| `orchestrator/output/` (gitignored runtime) | Local `episodic.md` mirror — runtime state, not committed. |

## 8. Where Freebuff is used (brain layer)

| Path | Role | Status |
|---|---|---|
| `fol/modules/llm/brain.py` — `FreebuffBrainAdapter` | Future primary brain behind `BrainInterface` | **DISABLED** — raises `BrainUnavailableError` ("no supported programmatic interface"); `FOL_BRAIN=freebuff` fails clearly, never silent fallback |
| `fol/modules/memory/brain.py` — `Brain` | Persistent Obsidian memory named "Freebuff Brain" | ✅ Active memory layer (name only — it is memory, not an LLM) |
| `~/.config/manicode/freebuff` CLI | Interactive TUI agent, model `deepseek/deepseek-v4-flash` | **No programmatic API** (audited: no `--prompt`/stdin/HTTP/SDK; internal endpoints undocumented) |

**Conclusion (unchanged from the prior audit):** Freebuff cannot be a runtime
brain yet. The abstraction (`BrainInterface` + `FreebuffBrainAdapter`
placeholder) is ready; the adapter activates only when Freebuff ships a
programmatic interface.

## 9. Current LLM routing (where the brain calls go today)

```
UI (SwiftUI) ──/chat SSE──▶ orchestrator/server.py ──llm_bridge──▶ get_brain("current")
                                                                        │
Web / API ──/api/chat──▶ fol/core/app.py ──modules/llm/engine.py / router.py
                                                                        ▼
                                              CurrentLLMAdapter ──▶ LiteLLMRouter
                                                                   (cloud-only
                                                                    OpenRouter chain)
   legacy resilience: analyze/_llm_async.py (only when fol/ unavailable)
```

## 10. Recommended unification sequence (for the NEXT phase command)

1. **One memory interface**: `MemoryInterface` with short-term context / working memory / Obsidian long-term; brain reads context ONLY through it. (Obsidian already canonical — formalize access points, kill scattered reads.)
2. **Unify proactive**: port `suggestion_engine` behavior into `fol/modules/llm/proactive.py`; orchestrator SSE emits from the FOL engine; remove the second engine (after tests).
3. **Unify context/screen**: move `context_engine/` functionality under `fol/modules/input/`; orchestrator consumes FOL context.
4. **Voice/TTS providers**: ElevenLabs/Whisper become providers behind FOL `/api/stt` + `modules/output/tts.py`; UI keeps `AudioRecorder` + a single STT endpoint.
5. **Freebuff**: remains disabled until a programmatic API exists; then implement `FreebuffBrainAdapter` (chat/chat_stream/acomplete/tools/stop-reason/timeouts) + routing `FOL_BRAIN=freebuff` → fallback chain.
6. **Do NOT delete** anything until each capability is migrated AND covered by tests; mark migrated parts legacy.

---

*Phase 1 audit complete. No code changed, nothing deleted, no git operations.*
