#!/usr/bin/env bash
# FOL v1.0-beta — demo harness.
#
# Runs all services and walks through the 5 core daily-use scenarios with a
# pause between each so you can screen-record and narrate the demo.
#
# Usage:
#   ./scripts/demo.sh                 # full demo, 25s pause between scenarios
#   DEMO_PAUSE=5 ./scripts/demo.sh    # shorter pauses
#   DEMO_QUICK=1 ./scripts/demo.sh    # no pauses (CI-style verification)
#
# The final response of every scenario is printed after each run.

set -u
cd "$(dirname "$0")/.." || exit 1

PAUSE="${DEMO_PAUSE:-25}"
QUICK="${DEMO_QUICK:-0}"

DEMO_SCENARIOS=(
  "Open Safari|open Safari"
  "Find the latest OpenAI news|find the latest news about OpenAI"
  "Remember I need to send the report tomorrow|remember that I need to send the report tomorrow"
  "Open the FOL project|open the FOL project in Finder"
  "Create a calendar event|create a calendar event for tomorrow at 10am called Team Meeting"
)

# Extract the last "complete" message from an SSE file (robust to \u escapes,
# embedded quotes and newlines — json.loads each data line directly).
extract_final_message() {
  python3 - "$1" <<'PY'
import json, sys
last = ""
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line.startswith("data: "):
        continue
    try:
        d = json.loads(line[6:])
    except Exception:
        continue
    if d.get("state") == "complete" and d.get("message"):
        last = d["message"].strip()
print(last)
PY
}

banner() {
  echo ""
  echo "=========================================================="
  echo "  $1"
  echo "=========================================================="
}

wait_health() {
  local port="$1" name="$2" tries=0
  until curl -s -m 2 "http://localhost:${port}/health" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -gt 20 ]; then
      echo "ERROR: $name (port $port) did not become healthy" >&2
      return 1
    fi
    sleep 2
  done
  echo "  ✓ $name healthy (port $port)"
}

cleanup() {
  [ -n "${ORCH_PID:-}" ] && kill "$ORCH_PID" 2>/dev/null
  [ -n "${AGENT_PID:-}" ] && kill "$AGENT_PID" 2>/dev/null
  [ -n "${FOL_PID:-}" ] && kill "$FOL_PID" 2>/dev/null
}

trap cleanup EXIT

banner "FOL v1.0-beta — Demo"
echo "Starting services…"

python3 orchestrator/server.py > /tmp/ss_demo_orch.log 2>&1 &
ORCH_PID=$!
python3 agent-server/server.py > /tmp/ss_demo_agent.log 2>&1 &
AGENT_PID=$!

wait_health 8420 "orchestrator" || exit 1
wait_health 8421 "agent-server" || exit 1

echo "All services up. Demo begins."
[ "$QUICK" = "0" ] && sleep "$PAUSE"

for entry in "${DEMO_SCENARIOS[@]}"; do
  TITLE="${entry%%|*}"
  MSG="${entry##*|}"
  banner "DEMO: $TITLE"
  echo "  User: \"$MSG\""
  [ "$QUICK" = "0" ] && sleep 3

  RESPONSE_FILE="/tmp/ss_demo_response.sse"
  curl -s -m 120 -N -X POST http://localhost:8420/chat \
    -H 'Content-Type: application/json' \
    -d "{\"message\": \"$MSG\"}" > "$RESPONSE_FILE" 2>&1

  TOOL_COUNT=$(grep -c '^event: tool_call' "$RESPONSE_FILE" || true)
  echo "  Tools called: $TOOL_COUNT"

  # Extract the final assistant message
  FINAL=$(extract_final_message "$RESPONSE_FILE")
  [ -z "$FINAL" ] && FINAL="(no text)"
  echo "  JARVIS: $FINAL"
  echo ""

  [ "$QUICK" = "0" ] && sleep "$PAUSE"
done

banner "Demo complete — all 5 scenarios executed"
echo "Logs: /tmp/ss_demo_orch.log, /tmp/ss_demo_agent.log"
