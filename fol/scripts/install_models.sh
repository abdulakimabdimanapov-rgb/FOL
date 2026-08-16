#!/usr/bin/env bash
# Install ML models for FOL
set -euo pipefail

echo "=== FOL Model Installer ==="
echo ""

DATA_DIR="${FOL_DATA_DIR:-$HOME/.fol}"
MODELS_DIR="$DATA_DIR/models"

mkdir -p "$MODELS_DIR"

echo "Models will be downloaded to: $MODELS_DIR"
echo ""

# Check for mlx-lm
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found"
    exit 1
fi

echo "--- Installing MLX Whisper model ---"
python3 -c "
import mlx_whisper
print('mlx-whisper is available')
" 2>/dev/null || echo "mlx-whisper not installed, skipping"

echo ""
echo "--- Checking MLX LM ---"
python3 -c "
try:
    import mlx_lm
    print('mlx-lm is available')
except ImportError:
    print('mlx-lm not installed, skipping')
" 2>/dev/null

echo ""
echo "--- Model installation complete ---"
echo ""
echo "To download a specific model, run:"
echo "  python3 -c \"from mlx_lm import load; load('mlx-community/Llama-3.2-3B-Instruct-4bit')\""
echo ""
echo "Or configure FOL to use cloud APIs:"
echo "  FOL_LLM_BACKEND=openai"
echo "  FOL_OPENAI_API_KEY=sk-..."
