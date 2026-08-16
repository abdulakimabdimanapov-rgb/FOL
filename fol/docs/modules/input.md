# Input Module

## Overview

The Input module handles all forms of user input: text, speech, screen capture, and vision.

## Components

| Component | Description |
|-----------|-------------|
| `TextInput` | Direct text input via CLI/API |
| `SpeechRecognizer` | Voice recognition via mlx-whisper |
| `ScreenCapture` | Screenshot capture via macOS APIs |
| `VisionAnalyzer` | Image analysis via MLX Vision |

## API

### TextInput

```python
from modules.input.text_input import TextInput

input_mod = TextInput()
text = await input_mod.read()
```

### SpeechRecognizer

```python
from modules.input.speech_recognizer import SpeechRecognizer, AudioChunk

recognizer = SpeechRecognizer(event_bus=event_bus, model_size="medium")
await recognizer.initialize()
text = await recognizer.transcribe(AudioChunk(data=audio_bytes))
```

### ScreenCapture

```python
from modules.input.screen_capture import ScreenCapture

capture = ScreenCapture()
screenshot = await capture.capture_full_screen()
```

### VisionAnalyzer

```python
from modules.input.vision import VisionAnalyzer

vision = VisionAnalyzer()
await vision.initialize()
description = await vision.analyze(screenshot)
```

## Configuration

```bash
FOL_STT_MODEL=medium       # tiny | base | small | medium | large
FOL_STT_DEVICE=mps         # cpu | mps
FOL_STT_LANGUAGE=ru        # ISO 639-1 language code
```
