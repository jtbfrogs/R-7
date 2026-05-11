#!/usr/bin/env python3
"""
scripts/test_chat.py
─────────────────────
Unified interactive chatbot — text mode by default, add --voice for full
voice I/O (speak to R-7 and hear it reply).  No robot hardware required.

Text mode
─────────
  python scripts/test_chat.py
  python scripts/test_chat.py --model gemma3:270m
  python scripts/test_chat.py --raw

Voice mode
──────────
  python scripts/test_chat.py --voice
  python scripts/test_chat.py --voice --continuous   # no Enter key needed
  python scripts/test_chat.py --voice --list-voices  # show available TTS voices
  python scripts/test_chat.py --voice --rate 140
  python scripts/test_chat.py --voice --vosk-model models/vosk-model-en-us-0.22

Voice prerequisites
───────────────────
  pip install vosk sounddevice pyttsx3
  # Linux:  sudo apt install espeak-ng libportaudio2
  # macOS:  brew install portaudio

  Vosk model (one-time download):
    bash scripts/download_vosk_model.sh
  Or manually:
    mkdir -p models && cd models
    wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
    unzip vosk-model-small-en-us-0.15.zip && mv vosk-model-small-en-us-0.15 vosk-model-small-en-us

General
───────
  Type / say 'quit' or press Ctrl-C to exit.
"""

import sys
import argparse
from pathlib import Path

# ── Make sure project root is on sys.path ─────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ai.ollama_client import OllamaClient, _sanitise, _SYSTEM_PROMPT


# ─── Argument parsing ─────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description     = "R-7 interactive chatbot (text + optional voice)",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Examples:\n"
            "  python scripts/test_chat.py\n"
            "  python scripts/test_chat.py --voice\n"
            "  python scripts/test_chat.py --voice --continuous\n"
            "  python scripts/test_chat.py --model gemma3:270m --voice\n"
        ),
    )
    # ── AI options ────────────────────────────────────────────────────────────
    p.add_argument("--model",   default=None, help="Override Ollama model (e.g. gemma3:270m)")
    p.add_argument("--raw",     action="store_true", help="Also print raw model output before sanitising")
    p.add_argument("--context", default="",  help="Optional context string injected into every prompt")

    # ── Voice options ─────────────────────────────────────────────────────────
    p.add_argument("--voice",       action="store_true", help="Enable voice I/O (STT + TTS)")
    p.add_argument("--continuous",  action="store_true", help="[voice] Always listening — no Enter key")
    p.add_argument("--vosk-model",  default="models/vosk-model-small-en-us",
                   metavar="PATH",  help="[voice] Path to Vosk model directory")
    p.add_argument("--rate",        type=int, default=155, metavar="WPM",
                   help="[voice] TTS speaking rate in words-per-minute (default: 155)")
    p.add_argument("--tts-voice",   default="", metavar="ID",
                   help="[voice] pyttsx3 voice ID (see --list-voices)")
    p.add_argument("--list-voices", action="store_true",
                   help="[voice] List available TTS voices and exit")
    return p.parse_args()


# ─── Voice helpers ─────────────────────────────────────────────────────────────

def _require_voice_deps() -> None:
    """Exit with a helpful message if voice dependencies are missing."""
    missing = []
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        missing.append("sounddevice  →  pip install sounddevice  (Linux: sudo apt install libportaudio2)")
    try:
        from vosk import Model  # noqa: F401
    except ImportError:
        missing.append("vosk         →  pip install vosk")
    try:
        import pyttsx3  # noqa: F401
    except ImportError:
        missing.append("pyttsx3      →  pip install pyttsx3  (Linux: sudo apt install espeak-ng)")

    if missing:
        print("\n✗ Missing voice dependencies:\n")
        for m in missing:
            print(f"    {m}")
        print()
        sys.exit(1)


def _list_voices_and_exit() -> None:
    import pyttsx3
    engine = pyttsx3.init()
    voices = engine.getProperty("voices") or []
    print(f"\n{len(voices)} TTS voices available:\n")
    for v in voices:
        print(f"  {v.id}")
    print()
    sys.exit(0)


def _init_stt(vosk_model_path: str):
    """Return a configured STTManager (engine lazily inited on first listen_once call)."""
    from audio.stt_manager import STTManager

    # Patch config just enough so STTManager picks the right engine + model
    from config.config_loader import get_config
    cfg = get_config()
    cfg["audio"]["stt_engine"]   = "vosk"
    cfg["audio"]["vosk_model_path"] = vosk_model_path

    stt = STTManager()
    # Verify the model path exists before we start the loop
    from pathlib import Path as _P
    if not _P(vosk_model_path).is_dir():
        print(f"\n✗ Vosk model not found at: {vosk_model_path}")
        print("  Download it with:")
        print("    bash scripts/download_vosk_model.sh")
        sys.exit(1)
    return stt


def _init_tts(voice_id: str, rate: int):
    """Return a configured TTSManager ready for speak_sync()."""
    from audio.tts_manager import TTSManager
    from config.config_loader import get_config
    cfg = get_config()
    cfg["audio"]["tts_engine"]   = "pyttsx3"
    cfg["audio"]["tts_rate_wpm"] = rate
    if voice_id:
        cfg["audio"]["tts_voice_id"] = voice_id
    return TTSManager()


# ─── Banner ───────────────────────────────────────────────────────────────────

def _print_banner(ai, args) -> None:
    mode = "voice" if args.voice else "text"
    listen = "continuous" if args.continuous else "push-to-talk (Enter)"
    print()
    print("══════════════════════════════════════════")
    print("  R-7 Chatbot")
    print("══════════════════════════════════════════")
    print(f"  Ollama model : {ai._model}")
    print(f"  Mode         : {mode}", end="")
    if args.voice:
        from pathlib import Path
        print(f"  [{listen}]")
        print(f"  Vosk model   : {Path(args.vosk_model).name}")
    else:
        print()
    if args.context:
        print(f"  Context      : {args.context}")
    print()
    if not args.voice:
        print("  System prompt:")
        for line in _SYSTEM_PROMPT.split(". "):
            if line.strip():
                print(f"    {line.strip()}")
        print()
    print("  Type / say 'quit' or press Ctrl-C to exit.")
    print("══════════════════════════════════════════\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    # ── Voice-only flags that exit early ──────────────────────────────────────
    if args.list_voices:
        _require_voice_deps()
        _list_voices_and_exit()

    # ── Check voice deps before doing anything else ───────────────────────────
    if args.voice:
        _require_voice_deps()

    # ── AI client ─────────────────────────────────────────────────────────────
    ai = OllamaClient()
    if args.model:
        ai._model    = args.model
        ai._available = None  # force re-check with new model name

    _print_banner(ai, args)

    if not ai.is_available():
        print("✗ Ollama is not available or model not loaded.")
        print(f"  Run: ollama pull {ai._model}")
        print( "       ollama serve")
        sys.exit(1)

    print(f"✓ Ollama ready  ({ai._model})\n")

    # ── Voice subsystems ──────────────────────────────────────────────────────
    stt = tts = None
    if args.voice:
        print("Initialising STT (Vosk)…", end=" ", flush=True)
        stt = _init_stt(args.vosk_model)
        # Trigger lazy model load now so the first listen_once is instant
        stt._init_vosk()
        print("ready.")

        print("Initialising TTS (pyttsx3)…", end=" ", flush=True)
        tts = _init_tts(args.tts_voice, args.rate)
        tts._init_engine()
        voice_name = (tts._engine.getProperty("voice") or "default").split(".")[-1] if tts._engine else "default"
        print(f"ready ({voice_name}).\n")

        tts.speak_sync("R-7 online. Hello!")

    # ─── Chat loop ────────────────────────────────────────────────────────────
    EXIT_WORDS = {"quit", "exit", "q", "goodbye", "bye"}

    try:
        while True:
            # ── Get input ─────────────────────────────────────────────────────
            if args.voice:
                if not args.continuous:
                    try:
                        input("[ Press Enter to speak, Ctrl-C to quit ]\n")
                    except EOFError:
                        break

                print("🎤  Listening…  (speak now)")
                user_input = stt.listen_once(timeout=8.0)

                if not user_input:
                    print("  (nothing heard — try again)\n")
                    continue

                print(f"You: {user_input}")
            else:
                try:
                    user_input = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nBye!")
                    break

            if not user_input:
                continue

            if user_input.lower() in EXIT_WORDS:
                if args.voice:
                    tts.speak_sync("Goodbye!")
                else:
                    print("Bye!")
                break

            # ── AI response ───────────────────────────────────────────────────
            if args.voice:
                print("R-7: (thinking…)")
            
            response = ai.ask(user_input, context=args.context or None)

            if not response:
                response = "Hmm, I am not sure about that."
                if args.raw:
                    print("R-7 [raw]: (no response)")

            if args.raw and not args.voice:
                # raw mode only meaningful in text mode (voice always shows clean output)
                raw = ai.ask(user_input, context=args.context or None)
                print(f"R-7 [raw]: {raw}")

            if args.voice:
                print(f"R-7 💬  {response}\n")
                tts.speak_sync(response)
            else:
                print(f"R-7: {response}\n")

    except KeyboardInterrupt:
        print("\nBye!")
        if args.voice and tts:
            tts.speak_sync("Bye!")


if __name__ == "__main__":
    main()
