#!/usr/bin/env python3
"""Quick test: ElevenLabs TTS with JARVIS voice (George)."""

import os
import sys
import json
import subprocess
import tempfile

# Voice ID for "George" — most JARVIS-like British male voice
JARVIS_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"

def main():
    api_key = os.environ.get("ELEVENLABS_API_KEY") or ""
    if not api_key:
        print("❌ ELEVENLABS_API_KEY not set!")
        print("   Export it or add to .env:")
        print('   export ELEVENLABS_API_KEY="your_key_here"')
        sys.exit(1)

    text = "Good morning, sir. I have analyzed your schedule and I am ready to assist."
    print(f"🔊 JARVIS says: \"{text}\"")
    print(f"   Voice: George (ID: {JARVIS_VOICE_ID})")
    print()

    # Build request
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{JARVIS_VOICE_ID}"
    headers = {
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.7,
            "similarity_boost": 0.75,
            "style": 0.1,
            "use_speaker_boost": True,
        },
    }

    # Save payload for debugging
    print("   Request payload:")
    print(f"   {json.dumps(payload, indent=2)}")
    print()

    # Write payload to temp file for curl
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        payload_path = f.name

    output_path = tempfile.mktemp(suffix=".mp3")

    try:
        # Use curl for simplicity
        cmd = [
            "curl", "-s", "-w", "\n%{http_code}",
            "-X", "POST", url,
            "-H", f"Content-Type: application/json",
            "-H", f"xi-api-key: {api_key}",
            "-d", f"@{payload_path}",
            "-o", output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        # Last line is status code
        lines = result.stdout.strip().split("\n")
        status_code = lines[-1].strip()
        print(f"   HTTP Status: {status_code}")

        if status_code == "200":
            import os as _os
            size = _os.path.getsize(output_path)
            print(f"✅ SUCCESS! Audio received: {size:,} bytes")
            print()
            print("   Play it with:")
            print(f"   afplay {output_path}")
            print()
            print("   Or open in Finder:")
            print(f"   open {output_path}")
        else:
            print(f"❌ Error: {result.stderr or 'See response above'}")
            if _os.path.exists(output_path) and _os.path.getsize(output_path) > 0:
                with open(output_path) as f:
                    print(f"   Response: {f.read()}")

    except subprocess.TimeoutExpired:
        print("❌ Request timed out (30s)")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        import os as _os
        if _os.path.exists(payload_path):
            _os.unlink(payload_path)

if __name__ == "__main__":
    main()
