"""STT providers — local (default) and opt-in cloud."""

from modules.input.voice.providers.elevenlabs import ElevenLabsSTT
from modules.input.voice.providers.mlx_whisper import MLXWhisperSTT

__all__ = ["MLXWhisperSTT", "ElevenLabsSTT"]
