#!/usr/bin/env bash
# Daily-usage scenario verification for FOL v1.0.
# Runs ALL servers + scenarios in ONE session (the terminal sandbox kills
# background processes between commands, so everything must be in one shot).
set -u
# Portable: resolve project root as the parent of this script's directory
# (no hardcoded /Users/... paths in the repo).
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1

SCENARIOS=(
  "open Safari and find the latest news about OpenAI|scenario_1"
  "write an email to my professor saying I will submit the report tomorrow|scenario_2"
  "create a calendar event for tomorrow at 10am called Team Meeting|scenario_3"
  "open the FOL project in Finder|scenario_4"
  "remember that I need to send the report tomorrow|scenario_5"
)

python3 orchestrator/server.py > /tmp/sc_orch.log 2>&1 &
OPID=$!
python3 agent-server/server.py > /tmp/sc_agent.log 2>&1 &
APID=$!
sleep 10

echo "=== AGENT HEALTH ==="
curl -s -m 3 http://localhost:8421/health | head -c 120
echo
echo "=== ORCH HEALTH ==="
curl -s -m 3 http://localhost:8420/health | head -c 200
echo

for entry in "${SCENARIOS[@]}"; do
  MSG="${entry%%|*}"
  TAG="${entry##*|}"
  echo "=========================================================="
  echo "SCENARIO $TAG: $MSG"
  echo "=========================================================="
  curl -s -m 90 -N -X POST http://localhost:8420/chat \
    -H 'Content-Type: application/json' \
    -d "{\"message\": \"$MSG\"}" > "/tmp/${TAG}.sse" 2>&1
  echo "--- event types ---"
  grep '^event:' "/tmp/${TAG}.sse" | sort | uniq -c
  echo "--- tool calls ---"
  grep -A0 'tool_call' "/tmp/${TAG}.sse" | head -6
  echo "--- final state ---"
  grep -A1 'complete\|error' "/tmp/${TAG}.sse" | grep 'message' | tail -1
  echo "--- guard fired? ---"
  grep -c 'loop guard\|Loop guard\|looping' /tmp/sc_orch.log || true
done

echo "=== SUMMARY OF TOOL USAGE PER SCENARIO ==="
for TAG in scenario_1 scenario_2 scenario_3 scenario_4 scenario_5; do
  TOOLS=$(grep 'tool_call' "/tmp/${TAG}.sse" | sed 's/.*"tool": "\([^"]*\)".*/\1/' | sort -u | tr '\n' ' ')
  FINAL=$(grep -A1 'complete\|error' "/tmp/${TAG}.sse" | grep 'message' | tail -1 | cut -c1-120)
  echo "${TAG}: tools=[${TOOLS}] final=${FINAL}"
done

kill $OPID $APID 2>/dev/null
true
