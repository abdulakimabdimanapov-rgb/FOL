// API client for the FastAPI backend (proxied through /api)

export interface FOLProfile {
  identity: { name: string; role: string; company: string };
  voice: {
    formality: string;
    avg_email_length: string;
    signature_phrases: string[];
    opens_with: string;
    closes_with: string;
    tone: string;
  };
  behavior: {
    work_hours: string;
    meeting_load: string;
    response_style: string;
    peak_focus_time: string;
  };
  context: {
    active_projects: string[];
    top_collaborators: string[];
    current_priorities: string[];
  };
}

export interface OnboardResponse {
  profile: FOLProfile;
  sources_used: string[];
  session_id: string;
  created_at: string;
}

export interface ActionTaken {
  tool: string;
  summary: string;
}

export interface ChatResponse {
  response: string;
  actions_taken: ActionTaken[];
}

export async function postOnboard(
  name: string,
  email: string,
  context: string,
  sessionId: string,
): Promise<OnboardResponse> {
  const res = await fetch("/api/onboard", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, context, session_id: sessionId }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function postChat(
  message: string,
  sessionId: string,
): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ─── SSE streaming chat (proxied to the orchestrator at :8420) ─────

export interface StreamCallbacks {
  onToken: (text: string) => void;
  onState: (state: string, message?: string) => void;
  /** Coarse, user-safe status — tool names/args are internal and never sent. */
  onActivity: (category: string, label: string) => void;
  onDone: (finalText: string) => void;
  onError: (error: string) => void;
}

/**
 * Client-side last line of defense: strip tool-call JSON structures from
 * streamed text so they can never render in the chat (mirrors the server-side
 * Response Formatter).
 */
function stripToolCallJson(text: string): string {
  // Remove ```json ... ``` fenced blocks that look like tool calls.
  let out = text.replace(/```json\s*(\{[\s\S]*?\})\s*```/g, (_, json: string) => {
    try {
      const obj = JSON.parse(json);
      return obj && typeof obj === "object" && "name" in obj ? "" : json;
    } catch {
      return json;
    }
  });
  // Remove bare tool-call JSON objects: {"type":"function","name":..., ...}
  out = out.replace(/\{\s*"type"\s*:\s*"function"[\s\S]*?\}/g, "");
  out = out.replace(/\{\s*"type"\s*:\s*"tool_use"[\s\S]*?\}/g, "");
  return out;
}

/**
 * Open a streaming chat session against the orchestrator's POST /chat
 * SSE endpoint. The Next.js route /api/chat/stream proxies to
 * http://localhost:8420/chat and pipes the event stream back.
 */
export async function streamChat(
  message: string,
  sessionId: string,
  cbs: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    cbs.onError(text || `HTTP ${res.status}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const finish = () => {
    // Guard against double-completion (e.g. a final "complete" state event
    // followed by a clean stream close). onDone must always fire so the UI
    // never stays stuck in the "thinking" state.
    if (!finished) {
      finished = true;
      cbs.onDone("");
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        finish();
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by a blank line
      const events = buffer.split(/\n\n/);
      buffer = events.pop() ?? "";

      for (const raw of events) {
        const evt = parseSseEvent(raw);
        if (!evt) continue;
        const isTerminal = handleSseEvent(evt.event, evt.data, cbs);
        if (isTerminal) finish();
      }
    }
  } catch (e) {
    if ((e as Error).name !== "AbortError") cbs.onError(String(e));
  } finally {
    finish();
    reader.releaseLock();
  }
}

function parseSseEvent(raw: string): { event: string; data: string } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}

function handleSseEvent(
  event: string,
  data: string,
  cbs: StreamCallbacks,
): boolean {
  // Returns true when this event is terminal (complete/error state) so the
  // caller can finalize the stream exactly once.
  try {
    const json = JSON.parse(data);
    switch (event) {
      case "token":
        cbs.onToken(stripToolCallJson(json.text ?? ""));
        return false;
      case "state":
        cbs.onState(json.state ?? "", json.message);
        if ((json.state === "complete" || json.state === "error") && json.message) {
          cbs.onDone(json.message);
          return true;
        }
        return false;
      case "activity":
        cbs.onActivity(json.category ?? "", json.label ?? "");
        return false;
      case "tool_call":
      case "tool_result":
      case "tool_progress":
        // Tool calls are internal actions — never surface them in the UI.
        return false;
      case "error":
        cbs.onError(json.message ?? data);
        return true;
      default:
        // component / tool_result / tool_progress — ignore for text rendering
        return false;
    }
  } catch {
    // non-JSON payload — ignore
    return false;
  }
}
