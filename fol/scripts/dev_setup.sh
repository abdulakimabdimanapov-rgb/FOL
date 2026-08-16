#!/usr/bin/env bash
# Development environment setup for FOL
set -euo pipefail

echo "=== FOL Development Setup ==="
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $PYTHON_VERSION"

REQUIRED_VERSION="3.12"
if [[ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]]; then
    echo "Error: Python $REQUIRED_VERSION+ required (found $PYTHON_VERSION)"
    exit 1
fi

echo ""

# Install uv if not present
if ! command -v uv &>/dev/null; then
    echo "Installing uv (fast Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "uv version: $(uv --version 2>/dev/null || echo 'not found')"
echo ""

# Install dependencies
echo "Installing dependencies..."
uv sync --all-groups

echo ""

# Create .env if not present
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "Please edit .env with your configuration"
fi

# Create data directories
DATA_DIR="${FOL_DATA_DIR:-$HOME/.fol}"
mkdir -p "$DATA_DIR/models"
mkdir -p "$DATA_DIR/vector_db"
mkdir -p "$DATA_DIR/logs"
mkdir -p "$DATA_DIR/cache"
mkdir -p "$DATA_DIR/recordings"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Run FOL:"
echo "  PYTHONPATH=. python3 -m core.app start --interactive"
echo ""
echo "Run tests:"
echo "  PYTHONPATH=. python3 -m pytest tests/ -v -n auto"
