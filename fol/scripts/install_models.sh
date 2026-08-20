#!/usr/bin/env bash
# Install ML models for FOL — STT only (mlx-whisper).
# Local LLMs (Ollama / MLX inference) are removed from FOL by policy.
set -euo pipefail

echo "=== FOL Model Installer (STT only) ==="
echo ""

DATA_DIR="${FOL_DATA_DIR:-$HOME/.fol}"
MODELS_DIR="$DATA_DIR/models"

mkdir -p "$MODELS_DIR"

echo "Models will be downloaded to: $MODELS_DIR"
echo ""

# Check for mlx-whisper (local speech-to-text)
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found"
    exit 1
fi

echo "--- Installing MLX Whisper model (STT) ---"
python3 -c "
import mlx_whisper
print('mlx-whisper is available')
" 2>/dev/null || echo "mlx-whisper not installed, skipping (voice STT will use cloud/local fallback)"

echo ""
echo "--- Model installation complete ---"
echo ""
echo "FOL does NOT run local LLMs. Reasoning goes through API providers only:"
echo "  FOL_BRAIN=current  (LiteLLMRouter — OpenRouter/OpenAI/Anthropic)"
echo "  FOL_OPENROUTER_API_KEY=sk-..."
