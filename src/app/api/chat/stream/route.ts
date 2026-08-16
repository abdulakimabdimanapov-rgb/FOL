import { NextRequest } from "next/server";

const ORCHESTRATOR_URL =
  process.env.ORCHESTRATOR_URL || "http://localhost:8420";

/**
 * Proxies a streaming chat request to the orchestrator (port 8420).
 * The orchestrator returns Server-Sent Events; this route forwards them
 * verbatim so the browser can consume the stream through the same-origin
 * /api path (avoids CORS and exposes no internal ports).
 */
export async function POST(req: NextRequest) {
  const body = await req.text();

  const res = await fetch(`${ORCHESTRATOR_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal: AbortSignal.timeout(180_000), // 3 minutes — long agent loops
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "Orchestrator unavailable");
    return new Response(text, { status: res.status });
  }

  // Pipe the SSE body straight through. Content-Type must stay text/event-stream.
  return new Response(res.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
