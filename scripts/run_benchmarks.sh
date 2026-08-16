#!/usr/bin/env bash
# ===========================================================================
# run_benchmarks.sh — CI benchmark suite for FOL test speed.
#
# Measures wall-clock time and memory for three test groups:
#   1) server core tests (130 tests)
#   2) entire test suite (816+ tests)
#   3) per-file breakdown
#
# Output: JSON Lines to stdout and to a timestamped file in benchmark/
# ===========================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BENCH_DIR="$PROJECT_ROOT/benchmark"
TIMESTAMP=$(date -u "+%Y-%m-%dT%H:%M:%SZ")
GH_REF="${GITHUB_REF:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo local)}"
GH_SHA="${GITHUB_SHA:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
RESULTS_FILE="$BENCH_DIR/results.jsonl"

mkdir -p "$BENCH_DIR"

# --- helpers ----------------------------------------------------------------

_bench() {
    local label="$1"   # unique label for this measurement
    shift
    local cmd=("$@")

    # Run tests once, capturing stdout (pytest output) and time metrics separately
    local stdout_file time_file
    stdout_file=$(mktemp)
    time_file=$(mktemp)

    # /usr/bin/time writes to stderr; pytest writes to stdout.
    # We redirect: pytest stdout → stdout_file, time's stderr → time_file
    /usr/bin/time -l "${cmd[@]}" > "$stdout_file" 2> "$time_file"
    local time_output
    time_output=$(cat "$time_file")
    rm -f "$time_file"

    # On macOS, `time -l` writes TWO lines:
    #        12.34 real         4.19 user         0.89 sys
    #           232243200  maximum resident set size
    local real_line mem_line
    real_line=$(echo "$time_output" | head -1)
    mem_line=$(echo "$time_output" | tail -1)

    local wall user sys mem
    wall=$(echo "$real_line" | awk '{print $1}')
    user=$(echo "$real_line" | awk '{print $4}')
    sys=$(echo "$real_line" | awk '{print $7}')
    mem=$(echo "$mem_line" | awk '{print $1}')

    # Extract pytest execution time from captured stdout
    local pytest_time passed
    pytest_time=$(grep -oE '[0-9]+\.[0-9]+s' < "$stdout_file" | tail -1 | tr -d 's')
    passed=$(grep -oE '[0-9]+ passed' < "$stdout_file" | grep -oE '[0-9]+' | tail -1)
    rm -f "$stdout_file"

    local record
    record=$(cat <<EOF
{
  "ts": "$TIMESTAMP",
  "ref": "$GH_REF",
  "sha": "$GH_SHA",
  "label": "$label",
  "tests_passed": ${passed:-0},
  "execution_seconds": ${pytest_time:-0},
  "wall_seconds": ${wall:-0},
  "user_cpu": ${user:-0},
  "sys_cpu": ${sys:-0},
  "peak_mem_kb": ${mem:-0}
}
EOF
)
    echo "$record"
    echo "$record" >> "$RESULTS_FILE"
}

PYTEST_OPTS=("--tb=short" "-q")
PYTEST_BASE=("python3" "-m" "pytest")

echo "=== FOL Benchmark: $TIMESTAMP ==="
echo "Ref: $GH_REF  Sha: $GH_SHA"
echo ""

# --- 1. Server core (fast path — 130 tests) --------------------------------
echo "--- 1. Server core tests ---"
_bench "server-core" \
    "${PYTEST_BASE[@]}" tests/test_chat_sse.py tests/test_orchestrator.py tests/test_memory_persistence.py \
    "${PYTEST_OPTS[@]}"

echo ""
echo "--- 2. Server core (parallel -n auto) ---"
_bench "server-core-parallel" \
    "${PYTEST_BASE[@]}" tests/test_chat_sse.py tests/test_orchestrator.py tests/test_memory_persistence.py \
    "${PYTEST_OPTS[@]}" "-n" "auto"

echo ""
echo "--- 3. Full suite ---"
_bench "full-suite" \
    "${PYTEST_BASE[@]}" tests/ \
    "${PYTEST_OPTS[@]}"

echo ""
echo "--- 4. Full suite (parallel -n auto) ---"
_bench "full-suite-parallel" \
    "${PYTEST_BASE[@]}" tests/ \
    "${PYTEST_OPTS[@]}" "-n" "auto"

echo ""
echo "=== Done. Results appended to $RESULTS_FILE ==="
