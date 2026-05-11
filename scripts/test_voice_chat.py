#!/usr/bin/env python3
"""
scripts/test_voice_chat.py
───────────────────────────
Voice chatbot tester — speak to R-7 and hear it reply.
No robot hardware required.

Flow
────
  1. Press Enter → start listening (or use --continuous to always listen)
  2. Speak your message
  3. R-7 sends it to Ollama and speaks the reply via TTS
  4. Repeat.  Ctrl-C or say "quit" to exit.

Dependencies (already in requirements.txt)
────────────────────────────────────────────
  pip install SpeechRecognition pyaudio pyttsx3
  brew install portaudio          # macOS (portaudio is required by pyaudio)

Usage
─────
  cd /Users/jtb/src/r-7
  source venv/bin/activate
  python scripts/test_voice_chat.py
  python scripts/test_voice_chat.py --model gemma3:270m --continuous
  python scripts/test_voice_chat.py --voice com.apple.eloquence.en-US.Eddy
  python scripts/test_voice_chat.py --list-voices    # show available TTS voices
"""

import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Imports with helpful error messages ───────────────────────────────────────
try:
    import speech_recognition as sr
except ImportError:
    print("✗ SpeechRecognition not installed.")
    print("  Run: pip install SpeechRecognition pyaudio")
    print("       brew install portaudio   (macOS)")
    sys.exit(1)

try:
    import pyttsx3
except ImportError:
    print("✗ pyttsx3 not installed.  Run: pip install pyttsx3")
    sys.exit(1)

from ai.ollama_client import OllamaClient


# ─── TTS helpers ─────────────────────────────────────────────────────────────

def list_voices():
    """Print all available pyttsx3 voices and exit."""
    engine = pyttsx3.init()
    voices = engine.getProperty("voices") or []
    print(f"\n{len(voices)} TTS voices available:\n")
    for v in voices:
        print(f"  {v.id}")
    print()
    sys.exit(0)


def make_tts_engine(voice_id: str = "", rate: int = 160, volume: float = 0.95):
    """Initialise a pyttsx3 engine with the given settings."""
    engine = pyttsx3.init()
    engine.setProperty("volume", volume)
    engine.setProperty("rate", rate)
    if voice_id:
        engine.setProperty("voice", voice_id)
    else:
        # Pick a decent English voice automatically
        voices = engine.getProperty("voices") or []
        for pref in ("en-US.Eddy", "en-US.Reed", "Samantha", "en-US", "english"):
            for v in voices:
                if pref.lower() in v.id.lower():
                    engine.setProperty("voice", v.id)
                    break
            else:
                continue
            break
    return engine


def speak(engine, text: str, stop_event: threading.Event):
    """Speak text; honours stop_event for interruption."""
    if stop_event.is_set():
        return
    print(f"R-7: {text}")
    engine.say(text)
    engine.runAndWait()


# ─── STT helpers ─────────────────────────────────────────────────────────────

def listen_once(recogniser: sr.Recognizer, mic: sr.Microphone,
                timeout: float = 6.0, phrase_limit: float = 8.0) -> str | None:
    """
    Record one phrase and return the recognised text (lowercase).
    Returns None on silence, unintelligible audio, or network error.
    """
    try:
        with mic as source:
            print("🎤 Listening…  (speak now)")
            audio = recogniser.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
        text = recogniser.recognize_google(audio)
        return text.strip().lower()
    except sr.WaitTimeoutError:
        print("  (no speech detected)")
        return None
    except sr.UnknownValueError:
        print("  (couldn't understand — try again)")
        return None
    except sr.RequestError as e:
        print(f"  ✗ Google STT error: {e}")
        return None


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="R-7 voice chatbot tester")
    p.add_argument("--model",       default=None,  help="Override Ollama model")
    p.add_argument("--voice",       default="",    help="pyttsx3 voice ID to use")
    p.add_argument("--rate",        type=int, default=160, help="TTS speaking rate (wpm)")
    p.add_argument("--continuous",  action="store_true",
                   help="Listen continuously without pressing Enter each time")
    p.add_argument("--list-voices", action="store_true",
                   help="Print available TTS voices and exit")
    p.add_argument("--context",     default="",    help="Optional context string for the AI")
    return p.parse_args()


def main():
    args = parse_args()

    if args.list_voices:
        list_voices()

    # ── TTS ──────────────────────────────────────────────────────────────────
    print("\nInitialising TTS…")
    tts = make_tts_engine(voice_id=args.voice, rate=args.rate)
    stop_speaking = threading.Event()

    # ── STT ──────────────────────────────────────────────────────────────────
    print("Initialising microphone…")
    recogniser = sr.Recognizer()
    mic = sr.Microphone()
    with mic as source:
        print("Calibrating for ambient noise…", end=" ", flush=True)
        recogniser.adjust_for_ambient_noise(source, duration=1.5)
        print("done.")

    # ── AI ───────────────────────────────────────────────────────────────────
    print("Connecting to Ollama…")
    ai = OllamaClient()
    if args.model:
        ai._model = args.model
        ai._available = None

    if not ai.is_available():
        print(f"✗ Ollama not available or model '{ai._model}' not loaded.")
        print(f"  Run: ollama pull {ai._model} && ollama serve")
        sys.exit(1)

    # ── Banner ───────────────────────────────────────────────────────────────
    mode = "continuous" if args.continuous else "push-to-talk (press Enter)"
    voice_name = tts.getProperty("voice") or "default"
    print()
    print("══════════════════════════════════════════")
    print("  R-7 Voice Chat Tester")
    print("══════════════════════════════════════════")
    print(f"  Model   : {ai._model}")
    print(f"  Voice   : {voice_name.split('.')[-1]}")
    print(f"  Mode    : {mode}")
    print("  Say 'quit' or press Ctrl-C to exit.")
    print("══════════════════════════════════════════\n")

    # Intro beep / greeting
    speak(tts, "R-7 online. Hello!", stop_speaking)

    # ── Main loop ─────────────────────────────────────────────────────────────
    try:
        while True:
            if not args.continuous:
                try:
                    input("[ Press Enter to speak, Ctrl-C to quit ]\n")
                except EOFError:
                    break

            # Listen
            stop_speaking.set()       # stop any ongoing speech before listening
            time.sleep(0.1)
            stop_speaking.clear()

            text = listen_once(recogniser, mic)
            if text is None:
                continue

            print(f"You: {text}")

            if text in ("quit", "exit", "goodbye", "bye"):
                speak(tts, "Goodbye!", stop_speaking)
                break

            # Get AI response
            print("R-7: (thinking…)")
            response = ai.ask(text, context=args.context or None)

            if response:
                speak(tts, response, stop_speaking)
            else:
                fallback = "Hmm, I'm not sure."
                speak(tts, fallback, stop_speaking)

            print()

    except KeyboardInterrupt:
        print("\nBye!")
        speak(tts, "Bye!", stop_speaking)


if __name__ == "__main__":
    main()
