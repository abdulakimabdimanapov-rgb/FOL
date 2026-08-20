"""Voice package — ONE speech interface with local-first STT providers."""

from modules.input.voice.interface import STTProvider
from modules.input.voice.stt import (
    available_providers,
    get_stt,
    transcribe_audio,
)
from modules.input.voice.engine import (
    VoiceEngine,
    VoiceState,
    WakeWordDetector,
    BackgroundListener,
)

__all__ = [
    "STTProvider",
    "get_stt",
    "available_providers",
    "transcribe_audio",
    "VoiceEngine",
    "VoiceState",
    "WakeWordDetector",
    "BackgroundListener",
]
