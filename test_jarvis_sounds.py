#!/usr/bin/env python3
"""
JARVIS Sound & Voice Test — FOL
=========================================
Тестирует звуковые эффекты (синтезированные, как в Swift AudioManager)
и Speech-to-Text через OpenAI Whisper.

Использование:
  python3 test_jarvis_sounds.py          # все звуки + микрофон
  python3 test_jarvis_sounds.py --sounds  # только звуки
  python3 test_jarvis_sounds.py --stt     # только микрофон
  python3 test_jarvis_sounds.py --tts     # ElevenLabs TTS (если есть ключ)
"""

import argparse
import os
import struct
import wave
import sys
import math
import random
import tempfile
from pathlib import Path
from typing import Optional

# ─── Audio playback ───────────────────────────────────────────────────────────

try:
    import sounddevice as sd
    import numpy as np
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SOUND SYNTHESIZER — JARVIS Sound Effects
#    (Python port of Swift SoundSynthesizer.swift)
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_RATE = 44100

def _make_wav(samples: list[float], filename: Optional[str] = None) -> bytes:
    """Convert float samples (-1..1) to WAV bytes. Optionally save to file."""
    num_samples = len(samples)
    data_size = num_samples * 2  # 16-bit mono
    buf = bytearray()

    # RIFF header
    buf += b'RIFF'
    buf += struct.pack('<I', 36 + data_size)
    buf += b'WAVE'

    # fmt chunk
    buf += b'fmt '
    buf += struct.pack('<I', 16)           # chunk size
    buf += struct.pack('<H', 1)            # PCM
    buf += struct.pack('<H', 1)            # mono
    buf += struct.pack('<I', SAMPLE_RATE)  # sample rate
    buf += struct.pack('<I', SAMPLE_RATE * 2)  # byte rate
    buf += struct.pack('<H', 2)            # block align
    buf += struct.pack('<H', 16)           # bits per sample

    # data chunk
    buf += b'data'
    buf += struct.pack('<I', data_size)
    for s in samples:
        clamped = max(-1.0, min(1.0, s))
        buf += struct.pack('<h', int(clamped * 32767))

    wav_bytes = bytes(buf)

    if filename:
        with open(filename, 'wb') as f:
            f.write(wav_bytes)
        print(f"  💾 Saved: {filename}")

    return wav_bytes


def activation_chime() -> bytes:
    """Rising electronic sweep — JARVIS activation.
       Frequency sweeps from 440Hz → 880Hz over 280ms."""
    duration = 0.28
    num_samples = int(SAMPLE_RATE * duration)
    samples = []

    for i in range(num_samples):
        t = i / SAMPLE_RATE
        progress = t / duration  # 0.0 → 1.0
        freq = 440.0 + (440.0 * progress)

        # Envelope
        fade_in = min(1.0, t / 0.015)
        fade_out = min(1.0, (duration - t) / 0.04)
        envelope = fade_in * fade_out

        fundamental = math.sin(2.0 * math.pi * freq * t)
        harmonic1 = 0.3 * math.sin(2.0 * math.pi * freq * 2.0 * t)
        sub_harmonic = 0.15 * math.sin(2.0 * math.pi * freq * 0.5 * t)

        value = envelope * 0.6 * (fundamental + harmonic1 + sub_harmonic)
        samples.append(value)

    return _make_wav(samples, "jarvis_activation.wav")


def confirmation_chime() -> bytes:
    """Two-tone descending 'bwoop-bwoop' — task complete.
       Tone 1: 880Hz (A5), Tone 2: 660Hz (E5)."""
    total_duration = 0.28
    num_samples = int(SAMPLE_RATE * total_duration)
    samples = []

    tone1_end = 0.10
    gap_end = 0.115
    tone2_end = 0.235

    for i in range(num_samples):
        t = i / SAMPLE_RATE
        value = 0.0

        if t < tone1_end:
            local_t = t
            local_dur = tone1_end
            env = min(1.0, local_t / 0.008) * min(1.0, (local_dur - local_t) / 0.012)
            tone = math.sin(2.0 * math.pi * 880.0 * t)
            fifth = 0.25 * math.sin(2.0 * math.pi * 1320.0 * t)
            value = env * 0.55 * (tone + fifth)

        elif t >= gap_end and t < tone2_end:
            local_t = t - gap_end
            local_dur = tone2_end - gap_end
            env = min(1.0, local_t / 0.008) * min(1.0, (local_dur - local_t) / 0.02)
            tone = math.sin(2.0 * math.pi * 660.0 * t)
            fifth = 0.2 * math.sin(2.0 * math.pi * 990.0 * t)
            value = env * 0.5 * (tone + fifth)

        elif t >= tone2_end and t < total_duration:
            local_t = t - tone2_end
            tail_dur = total_duration - tone2_end
            env = max(0.0, 1.0 - local_t / tail_dur)
            reverb = 0.08 * math.sin(2.0 * math.pi * 660.0 * t * 0.97)
            value = env * reverb

        samples.append(value)

    return _make_wav(samples, "jarvis_confirmation.wav")


def boot_chime() -> bytes:
    """Grand JARVIS boot chime — ascending arpeggio C4→E4→G4→C5 over 920ms."""
    duration = 0.92
    num_samples = int(SAMPLE_RATE * duration)
    samples = []

    notes = [
        (261.63, 0.00, 0.22),  # C4
        (329.63, 0.20, 0.44),  # E4
        (392.00, 0.40, 0.66),  # G4
        (523.25, 0.60, 0.86),  # C5
    ]

    for i in range(num_samples):
        t = i / SAMPLE_RATE
        value = 0.0

        for freq, start, end in notes:
            if t < start or t >= end:
                continue
            local_t = t - start
            local_dur = end - start
            attack = min(1.0, local_t / 0.02)
            release = min(1.0, (local_dur - local_t) / 0.04)
            envelope = attack * release

            fundamental = math.sin(2.0 * math.pi * freq * t)
            octave = 0.3 * math.sin(2.0 * math.pi * freq * 2.0 * t)
            fifth = 0.15 * math.sin(2.0 * math.pi * freq * 1.5 * t)

            value += envelope * 0.45 * (fundamental + octave + fifth)

        # Global fade
        fade_in = min(1.0, t / 0.04)
        fade_out = min(1.0, (duration - t) / 0.08)
        global_env = fade_in * fade_out

        samples.append(value * global_env)

    return _make_wav(samples, "jarvis_boot_chime.wav")


def hud_click() -> bytes:
    """Crisp HUD interface click — 18ms high-frequency tap."""
    duration = 0.018
    num_samples = int(SAMPLE_RATE * duration)
    samples = []

    for i in range(num_samples):
        t = i / SAMPLE_RATE
        progress = t / duration
        envelope = math.exp(-progress * 12.0)

        tone1 = math.sin(2.0 * math.pi * 2400.0 * t)
        tone2 = 0.5 * math.sin(2.0 * math.pi * 3600.0 * t)
        noise = 0.3 * random.uniform(-1.0, 1.0)

        value = envelope * 0.5 * (tone1 + tone2 + noise)
        samples.append(value)

    return _make_wav(samples, "jarvis_hud_click.wav")


def play_wav(wav_bytes: bytes, label: str):
    """Play WAV bytes through speakers."""
    if not HAS_SOUNDDEVICE:
        print(f"  ⚠️  Install sounddevice: pip3 install sounddevice")
        return

    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        f.write(wav_bytes)
        tmp_path = f.name

    try:
        import soundfile as sf
        data, sr = sf.read(tmp_path)
        print(f"  🔊 Playing '{label}' ({len(data)/sr:.2f}s)...")
        sd.play(data, sr)
        sd.wait()
        print(f"  ✅ Done\n")
    except Exception as e:
        print(f"  ❌ Playback error: {e}")
    finally:
        os.unlink(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. STT — Speech-to-Text via OpenAI Whisper
# ═══════════════════════════════════════════════════════════════════════════════

def load_env() -> dict:
    """Load .env file from project root."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        print("⚠️  .env not found — API keys unavailable")
        return {}

    env = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, val = line.partition('=')
                env[key.strip()] = val.strip()
    return env


ENV = load_env()
OPENAI_KEY = ENV.get('OPENAI_API_KEY', '')
ELEVENLABS_KEY = ENV.get('ELEVENLABS_API_KEY', '')


def test_stt_whisper():
    """Record from mic and transcribe via OpenAI Whisper."""
    if not OPENAI_KEY:
        print("❌ OPENAI_API_KEY не найден в .env")
        print("   Добавь: OPENAI_API_KEY=sk-...")
        return

    if not HAS_SOUNDDEVICE:
        print("❌ Нужен sounddevice: pip3 install sounddevice soundfile")
        return

    print("\n" + "="*55)
    print("🎤  JARVIS STT TEST — OpenAI Whisper")
    print("="*55)
    print("Говори что-нибудь после сигнала...")
    print("  (3 секунды записи)\n")

    import soundfile as sf

    fs = 16000  # Whisper expects 16kHz
    print("🔴 Запись...", end=' ', flush=True)
    try:
        recording = sd.rec(int(3 * fs), samplerate=fs, channels=1, dtype='int16')
        sd.wait()
        print("Готово! Обработка...")
    except Exception as e:
        print(f"\n❌ Ошибка записи: {e}")
        print("   Проверь микрофон в System Settings > Privacy > Microphone")
        return

    # Save to temp WAV file
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        sf.write(f.name, recording, fs)
        tmp_path = f.name

    try:
        # Call Whisper API
        import requests
        with open(tmp_path, 'rb') as f:
            print("  📡 Отправка в Whisper API...")
            resp = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                files={"file": ("recording.wav", f, "audio/wav")},
                data={"model": "whisper-1", "language": "en"},
                timeout=30,
            )

        if resp.status_code == 200:
            text = resp.json().get("text", "")
            print(f"\n  ✨ JARVIS HEARD: \"{text}\"")
            print(f"  ✅ STT работает! ({len(text)} chars)\n")
        elif resp.status_code == 401:
            print("  ❌ Неверный API ключ OpenAI")
        else:
            print(f"  ❌ Ошибка {resp.status_code}: {resp.text[:200]}")

    except Exception as e:
        print(f"  ❌ Ошибка сети: {e}")
    finally:
        os.unlink(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TTS — ElevenLabs JARVIS Voice (опционально)
# ═══════════════════════════════════════════════════════════════════════════════

def test_tts_elevenlabs_if_available():
    """Test ElevenLabs TTS with JARVIS voice if API key is available."""
    if not ELEVENLABS_KEY:
        print("\n" + "="*55)
        print("🔇  ELEVENLABS TTS — ключ не найден")
        print("="*55)
        print("JARVIS голос требует ELEVENLABS_API_KEY в .env")
        print()
        print("  Как получить:")
        print("    1. https://elevenlabs.io → Sign Up")
        print("    2. Profile → API Keys → Create")
        print('    3. Добавь в .env: ELEVENLABS_API_KEY=sk_...')
        print()
        print("  После добавления ключа:")
        print("    python3 test_jarvis_sounds.py --tts")
        print()
        return

    if not HAS_REQUESTS:
        print("❌ Нужен requests: pip3 install requests")
        return

    print("\n" + "="*55)
    print("🔊  JARVIS TTS TEST — ElevenLabs")
    print("="*55)

    voice_id = "JBFqnCBsd6RMkjVDRZzb"  # George — JARVIS-like voice
    text = "Good morning, sir. All systems are operational. How may I assist you today?"

    print(f"  Voice: George (JARVIS)")
    print(f"  Text:  \"{text}\"")
    print(f"  📡 Sending TTS request...")

    try:
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": ELEVENLABS_KEY,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.7,
                    "similarity_boost": 0.75,
                    "style": 0.1,
                    "use_speaker_boost": True,
                },
            },
            timeout=30,
        )

        if resp.status_code == 200:
            # Save and play
            wav_path = "jarvis_tts_test.mp3"
            with open(wav_path, 'wb') as f:
                f.write(resp.content)
            print(f"  💾 Saved: {wav_path} ({len(resp.content)/1024:.1f} KB)")

            # Try to play with afplay (macOS built-in)
            print("  🔊 Playing with afplay...")
            os.system(f"afplay '{wav_path}' &>/dev/null &")
            print("  ✅ TTS работает! \n")
        elif resp.status_code == 401:
            print("  ❌ Неверный ElevenLabs API ключ")
        else:
            print(f"  ❌ Ошибка {resp.status_code}")

    except Exception as e:
        print(f"  ❌ Ошибка: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def test_sounds():
    """Play all 4 JARVIS sound effects."""
    print("\n" + "="*55)
    print("🎵  JARVIS SOUND EFFECTS TEST")
    print("="*55)

    if not HAS_SOUNDDEVICE:
        print("⚠️  Sound device not available — saving WAV files only")
        print("   Install: pip3 install sounddevice soundfile")
        print("   Then play: afplay jarvis_boot_chime.wav\n")
        boot_chime()
        activation_chime()
        confirmation_chime()
        hud_click()
        print("\n✅ WAV files saved! Play with:")
        print("   afplay jarvis_boot_chime.wav")
        print("   afplay jarvis_activation.wav")
        print("   afplay jarvis_confirmation.wav")
        print("   afplay jarvis_hud_click.wav")
        return

    print("🔊 Проверь громкость наушников/колонок!\n")

    # 1. Boot chime
    print("1/4: JARVIS Boot Chime 🚀")
    play_wav(boot_chime(), "Boot Chime")

    # 2. Activation chime
    print("2/4: JARVIS Activation ⚡")
    play_wav(activation_chime(), "Activation")

    # 3. Confirmation chime
    print("3/4: JARVIS Confirmation ✅")
    play_wav(confirmation_chime(), "Confirmation")

    # 4. HUD click (x3 for demo)
    print("4/4: JARVIS HUD Click 🖱️")
    for _ in range(3):
        play_wav(hud_click(), "HUD Click")
    print()

    print("✅ Все 4 звука JARVIS протестированы!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JARVIS Sound & Voice Test")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--sounds", action="store_true", help="Only test sound effects")
    group.add_argument("--stt", action="store_true", help="Only test speech-to-text (mic → Whisper)")
    group.add_argument("--tts", action="store_true", help="Only test ElevenLabs TTS voice")
    args = parser.parse_args()

    if args.sounds:
        test_sounds()
    elif args.stt:
        test_stt_whisper()
    elif args.tts:
        test_tts_elevenlabs_if_available()
    else:
        # Run all
        test_sounds()
        test_stt_whisper()
        if ELEVENLABS_KEY:
            test_tts_elevenlabs_if_available()
        else:
            test_tts_elevenlabs_if_available()  # Shows instructions

    print("\n➡️  Теперь открой приложение в Xcode и запусти!")
