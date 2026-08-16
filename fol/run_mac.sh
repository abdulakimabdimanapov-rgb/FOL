#!/bin/bash
# Quick launch FOL macOS App
cd "$(dirname "$0")"

# Check if server is already running
if lsof -i :8754 -sTCP:LISTEN > /dev/null 2>&1; then
    echo "FOL server already running on port 8754"
    open "http://127.0.0.1:8754/"
else
    echo "Starting FOL..."
    python3 run_api_server.py &
    sleep 2
    open "http://127.0.0.1:8754/"
    wait
fi
