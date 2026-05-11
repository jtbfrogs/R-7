#!/usr/bin/env python3
"""
scripts/test_voice_chat.py
───────────────────────────
Voice chatbot tester — speak to R-7 and hear it reply.
No robot hardware required.  Works on Pop!_OS Linux and macOS.

Flow
────
  1. Press Enter to start listening (or --continuous to always listen)
  2. Speak your message
  3. R-7 sends it to Ollama and speaks the reply via TTS
  4. Repeat.  Ctrl-C or say "quit" to exit.

STT backend
────────────
  Uses Vosk (fully offline) with a small downloaded model.
  Download the model once:
    mkdir -p models && cd models
    wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
    unzip vosk-model-small-en-us-0.15.zip
    mv vosk-model-small-en-us-0.15 vosk-model-small-en-us

  Or use the helper script:
    bash scripts/download_vosk_model.sh

Dependencies
────────────
  pip install vosk sounddevice pyttsx3
  # Linux:  sudo apt install espeak-ng libportaudio2
  # macOS:  brew install portaudio

Usage
─────
  cd /path/to/r-7
  source venv/bin/activate
  python scripts/test_voice_chat.py
  python scripts/test_voice_chat.py --continuous
  python scripts/test_voice_chat.py --model gemma3:270m
  python scripts/test_voice_chat.py --model-path models/vosk-model-en-us-0.22  # larger model
  python scripts/test_voice_chat.py --list-voices
"""

import argparse
import json
import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Dependency checks ─────────────────────────────────────────────────────────
try:
    import sounddevice as sd
except ImportError:
    print("✗ sounddevice not installed.")
    print("  Run: pip install sounddevice")
    print("  Linux: sudo apt install libportaudio2")
    sys.exit(1)

try:
    from vosk import Model, KaldiRecognizer
except ImportError:
    print("✗ vosk not installed.  Run: pip install vosk")
    sys.exit(1)

try:
    import pyttsx3
except ImportError:
    print("✗ pyttsx3 not installed.  Run: pip install pyttsx3")
    print("  Linux: sudo apt install espeak-ng")
    sys.exit(1)

from ai.ollama_client import OllamaClient

# ─── Constants ────────────────────────────────────────────────────────────────
DEFAULT_VOSK_MODEL = "models/vosk-model-small-en-us"
SAMPLE_RATE        = 16000    # Hz — Vosk expects 16 kHz mono
BLOCK_SIZE         = 8000     # frames per sounddevice block (~0.5 s)


# ─── TTS ──────────────────────────────────────────────────────────────────────

def list_voices() -> None:
    engine = pyttsx3.init()
    voices = engine.getProperty("voices") or []
    print(f"\n{len(voices)} TTS voices available:\n")
    for v in voices:
        print(f"  {v.id}")
    print()
    sys.exit(0)


def make_tts(voice_id: str = "", rate: int = 155):
    engine = pyttsx3.init()
    engine.setProperty("volume", 0.95)
    engine.setProperty("rate",   rate)

    if voice_id:
        engine.setProperty("voice", voice_id)
    else:
        voices = engine.getProperty("voices") or []
        # Preference order — first match wins
        prefs = [
            "en-US.Eddy", "en-US.Reed", "en-US.Rocko",  # macOS eloquence
            "en-us",                                       # espeak-ng en-us
            "mb-us2", "mb-us1", "mb-en1",                 # mbrola (Linux)
            "Samantha",                                    # macOS compact
        ]
        for pref in prefs:
            for v in voices:
                if pref.lower() in v.id.lower():
                    engine.setProperty("voice", v.id)
                    break
            else:
                continue
            break

    return engine


def speak(tts, text: str) -> None:
    print(f"R-7 💬  {text}")
    tts.say(text)
    tts.runAndWait()


# ─── STT (Vosk + sounddevice) ─────────────────────────────────────────────────

def load_vosk(model_path: str) -> Model:
    path = Path(model_path)
    if not path.is_dir():
        print(f"\n✗ Vosk model not found at: {path}")
        print("  Download it once with:")
        print("    bash scripts/download_vosk_model.sh")
        print("  Or manually:")
        print("    mkdir -p models && cd models")
        print("    wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip")
        print("    unzip vosk-model-small-en-us-0.15.zip")
        print("    mv vosk-model-small-en-us-0.15 vosk-model-small-en-us")
        sys.exit(1)
    print(f"Loading Vosk model from {path}…", end=" ", flush=True)
    model = Model(str(path))
    print("ready.")
    return model


def listen_once(model: Model, timeout: float = 8.0) -> str | None:
    """
    Record audio until a complete phrase is detected (or timeout).
    Returns recognised text (lowercase), or None on silence/failure.
    """
    rec      = KaldiRecognizer(model, SAMPLE_RATE)
    audio_q: queue.Queue = queue.Queue()
    result_text: list[str] = []
    deadline = time.time() + timeout

    def audio_callback(indata, frames, time_info, status):
        audio_q.put(bytes(indata))

    with sd.RawInputStream(
        samplerate = SAMPLE_RATE,
        blocksize  = BLOCK_SIZE,
        dtype      = "int16",
        channels   = 1,
        callback   = audio_callback,
    ):
        print("🎤  Listening…  (speak now)")
        while time.time() < deadline:
            try:
                data = audio_q.get(timeout=0.3)
            except queue.Empty:
                continue

            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text   = result.get("text", "").strip().lower()
                if text:
                    return text
                # empty result — keep listening
            # else: partial — keep going

    # Timeout: check final partial result
    final = json.loads(rec.FinalResult()).get("text", "").strip().lower()
    return final if final else None


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="R-7 voice chatbot tester")
    p.add_argument("--model",      default=None,              help="Ollama model to use")
    p.add_argument("--model-path", default=DEFAULT_VOSK_MODEL, help="Path to Vosk model directory")
    p.add_argument("--voice",      default="",                help="pyttsx3 voice ID")
    p.add_argument("--rate",       type=int, default=155,     help="TTS speaking rate (wpm)")
    p.add_argument("--continuous", action="store_true",       help="Listen continuously without pressing Enter")
    p.add_argument("--context",    default="",                help="Optional context string for the AI")
    p.add_argument("--list-voices",action="store_true",       help="List TTS voices and exit")
    return p.parse_args()


def main():
    args = parse_args()

    if args.list_voices:
        list_voices()

    # ── Init TTS ─────────────────────────────────────────────────────────────
    print("\nInitialising TTS…", end=" ", flush=True)
    tts = make_tts(voice_id=args.voice, rate=args.rate)
    voice_name = (tts.getProperty("voice") or "default").split(".")[-1]
    print(f"ready ({voice_name}).")

    # ── Init STT ─────────────────────────────────────────────────────────────
    vosk_model = load_vosk(args.model_path)

    # ── Init AI ──────────────────────────────────────────────────────────────
    print("Connecting to Ollama…", end=" ", flush=True)
    ai = OllamaClient()
    if args.model:
        ai._model    = args.model
        ai._available = None
    if not ai.is_available():
        print(f"\n✗ Ollama not available or model '{ai._model}' not loaded.")
        print(f"  Run: ollama pull {ai._model} && ollama serve")
        sys.exit(1)
    print(f"ready ({ai._model}).")

    # ── Banner ───────────────────────────────────────────────────────────────
    mode = "continuous" if args.continuous else "push-to-talk (press Enter)"
    print()
    print("══════════════════════════════════════════")
    print("  R-7 Voice Chat Tester")
    print("══════════════════════════════════════════")
    print(f"  Ollama model : {ai._model}")
    print(f"  Vosk model   : {Path(args.model_path).name}")
    print(f"  TTS voice    : {voice_name}")
    print(f"  Mode         : {mode}")
    print("  Say 'quit' or press Ctrl-C to exit.")
    print("══════════════════════════════════════════\n")

    speak(tts, "R-7 online. Hello!")

    # ── Main loop ─────────────────────────────────────────────────────────────
    try:
        while True:
            if not args.continuous:
                try:
                    input("[ Press Enter to speak, Ctrl-C to quit ]\n")
                except EOFError:
                    break

            text = listen_once(vosk_model)

            if not text:
                print("  (nothing heard — try again)\n")
                continue

            print(f"You: {text}")

            if text in ("quit", "exit", "goodbye", "bye"):
                speak(tts, "Goodbye!")
                break

            print("R-7: (thinking…)")
            response = ai.ask(text, context=args.context or None)
            speak(tts, response or "Hmm, I am not sure.")
            print()

    except KeyboardInterrupt:
        print("\nBye!")
        speak(tts, "Bye!")


if __name__ == "__main__":
    main()
