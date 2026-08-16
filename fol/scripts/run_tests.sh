#!/usr/bin/env bash
# Run FOL test suite
set -euo pipefail

echo "=== FOL Test Suite ==="
echo ""

# Default to all tests
TEST_PATH="${1:-tests/}"

PYTHONPATH=. python3 -m pytest "$TEST_PATH" -v --tb=short --timeout=30 -n auto "$@"
