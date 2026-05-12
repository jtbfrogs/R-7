"""
main.py
────────
R-7 Droid — Main entry point.

Starts every subsystem in the correct order, hands off to the
behaviour manager, and handles clean shutdown on Ctrl+C or errors.

Usage
─────
    python main.py                              # full autonomous mode
    python main.py --no-vision                  # run without HuskyLens
    python main.py --no-ai                      # run without Ollama
    python main.py --no-behaviour               # connect + speak, no movement
    python main.py --port /dev/ttyUSB0          # override serial port
    python main.py --debug                      # verbose logging

Voice chat modes (Vosk STT + pyttsx3 TTS):
    python main.py --voice --no-roomba          # voice chat, no hardware needed
    python main.py --voice --no-roomba --continuous   # always-listening mode
    python main.py --voice                      # voice + full Roomba hardware
    python main.py --voice --vosk-model models/vosk-model-en-us-0.22  # large model

First-time voice setup:
    bash scripts/download_vosk_model.sh         # download the Vosk model (~40 MB)
    pip install vosk sounddevice pyttsx3        # install voice dependencies

For interactive control:
    python commands/command_console.py

For Roomba-only serial testing:
    python roomba/roomba_test.py
"""

import sys
import time
import signal
import argparse

from roomba.controller          import RoombaController
from huskylens.huskylens_manager import HuskyLensManager
from ai.personality             import Personality
from ai.ollama_client           import OllamaClient
from ai.voice_chat              import VoiceChatManager
from audio.tts_manager          import TTSManager
from audio.stt_manager          import STTManager
from behaviors.behavior_manager import BehaviorManager, BehaviorState
from utilities.logger           import get_logger, set_global_level
from config.config_loader       import get_config, dump_config

log = get_logger(__name__)

# ─── Colour helpers ──────────────────────────────────────────────────────────
def _c(t, c):
    codes = {"green":"\033[32m","red":"\033[31m","yellow":"\033[33m",
             "cyan":"\033[36m","bold":"\033[1m","reset":"\033[0m"}
    return f"{codes.get(c,'')}{t}{codes['reset']}"


def _banner() -> None:
    print(_c("""
  ██████╗       ███████╗
  ██╔══██╗      ╚════██║
  ██████╔╝          ██╔╝
  ██╔══██╗         ██╔╝
  ██║  ██║         ██║
  ╚═╝  ╚═╝         ╚═╝
  R-7 Droid  v0.1.0
""", "cyan"))


def main(args: argparse.Namespace) -> int:
    """
    Main application lifecycle.
    Returns exit code: 0 = clean exit, 1 = error.
    """
    _banner()
    cfg = get_config()
    log.info("R-7 Droid starting up...")
    log.debug("Active config:\n%s", dump_config())

    # ─── Voice-only mode (no Roomba hardware required) ────────────────────────
    # --continuous always means voice-only (no hardware loop)
    if args.continuous:
        args.voice     = True
        args.no_roomba = True
    if args.voice and args.no_roomba:
        return _run_voice_only(args)

    # ─── Instantiate subsystems ─────────────────────────────────────────────
    roomba      = RoombaController()
    tts         = TTSManager()
    personality = Personality()
    ai_client   = OllamaClient()
    husky:      HuskyLensManager | None = None
    stt:        STTManager       | None = None
    behavior:   BehaviorManager  | None = None
    voice_chat: VoiceChatManager | None = None

    # ─── Shutdown handler ────────────────────────────────────────────────────
    _shutdown_requested = [False]

    def _handle_signal(sig, frame):
        if not _shutdown_requested[0]:
            log.info("Shutdown signal received (%s)", sig)
            _shutdown_requested[0] = True

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # ─── Start TTS ──────────────────────────────────────────────────────────
    log.info("[1/5] Starting TTS...")
    if not tts.start():
        log.warning("TTS failed — continuing without speech")

    # ─── Start Roomba ────────────────────────────────────────────────────────
    log.info("[2/5] Connecting to Roomba...")
    port = args.port or None
    if not roomba.startup(port):
        log.error("Cannot connect to Roomba — aborting")
        log.error("  Try: python roomba/roomba_test.py  for diagnostics")
        tts.stop()
        return 1
    log.info("Roomba connected in %s mode", roomba.state.name)

    # ─── Start HuskyLens ─────────────────────────────────────────────────────
    if not args.no_vision:
        log.info("[3/5] Starting HuskyLens sensor...")
        husky = HuskyLensManager()
        if not husky.start():
            log.warning("HuskyLens failed — running without vision")
            husky = None
        else:
            log.info("HuskyLens running — algorithm: %s", husky.current_algorithm)

    # ─── Check AI ────────────────────────────────────────────────────────────
    if not args.no_ai:
        log.info("[4/5] Checking AI (Ollama)...")
        if ai_client.is_available():
            log.info("AI available — model: %s", cfg["ai"]["model"])
        else:
            log.warning("AI unavailable — personality phrases only")

    # ─── Start STT / Voice Chat ──────────────────────────────────────────────
    if args.voice:
        log.info("Starting voice chat (Vosk STT + pyttsx3 TTS)...")
        voice_chat = VoiceChatManager(
            vosk_model_path = args.vosk_model,
            tts_rate        = 155,
            ai_client       = ai_client,
            personality     = personality,
            use_wake_word   = False,   # no wake word needed in hardware mode
        )
        if not voice_chat.init():
            log.error("Voice chat init failed — continuing without voice input")
            voice_chat = None
        else:
            if not voice_chat.start_background(
                tts_manager        = tts,
                interrupt_callback = tts.interrupt,
            ):
                log.warning("Voice chat background start failed")
                voice_chat = None
            else:
                log.info("Voice chat running (always listening)")
    elif cfg["audio"].get("voice_input_enabled", False):
        # Legacy config-driven path (wake word, background thread)
        log.info("Starting STT (voice input, config-driven)...")
        stt = STTManager()
        stt.set_interrupt_callback(tts.interrupt)

        def _on_voice_command(text: str):
            log.info("Voice command: %s", text)
            response = ai_client.ask(text) if ai_client.is_available() else None
            phrase   = personality.filter_ai_response(response) if response else personality.react("confused")
            tts.speak(phrase, priority=True)
            personality.mark_spoke()

        stt.set_callback(_on_voice_command)
        stt.start()

    # ─── Start Behaviours ────────────────────────────────────────────────────
    if not args.no_behaviour and husky:
        log.info("[5/5] Starting behaviour manager...")
        behavior = BehaviorManager(
            roomba      = roomba,
            husky       = husky,
            tts         = tts,
            personality = personality,
            ai_client   = ai_client if not args.no_ai else None,
        )
        behavior.start()
    else:
        log.info("[5/5] Behaviour manager skipped (--no-behaviour or no HuskyLens)")

    # ─── Startup greeting ────────────────────────────────────────────────────
    greeting = personality.greeting()
    log.info("Startup greeting: %s", greeting)
    tts.speak(greeting)

    # ─── Main loop ───────────────────────────────────────────────────────────
    log.info("R-7 is running — press Ctrl+C to stop")
    print(_c("\n  R-7 is running. Press Ctrl+C to stop.\n", "green"))

    heartbeat_interval = 30.0   # log a heartbeat every 30 seconds
    last_heartbeat     = time.time()

    while not _shutdown_requested[0]:
        now = time.time()

        # Periodic heartbeat log
        if now - last_heartbeat >= heartbeat_interval:
            last_heartbeat = now
            b_state = behavior.state.name if behavior else "N/A"
            h_state = "target" if (husky and husky.get_state().any_target_detected) else "none"
            log.info(
                "Heartbeat | Roomba: %s | Behaviour: %s | HuskyLens: %s",
                roomba.state.name, b_state, h_state,
            )

        time.sleep(0.1)

    # ─── Clean shutdown ──────────────────────────────────────────────────────
    log.info("Shutting down R-7...")
    farewell = personality.farewell()
    tts.speak(farewell, priority=True)
    time.sleep(1.5)   # let farewell finish

    if behavior:
        behavior.stop()
    if husky:
        husky.stop()
    if voice_chat:
        voice_chat.stop()
    if stt:
        stt.stop()
    tts.stop()
    roomba.shutdown()

    log.info("R-7 shutdown complete")
    print(_c("\n  R-7 offline. Goodbye!\n", "cyan"))
    return 0


# ─── Voice-only entry point ───────────────────────────────────────────────────

def _run_voice_only(args: argparse.Namespace) -> int:
    """
    Run a standalone interactive voice chat session — no Roomba required.
    Activated by:  python main.py --voice --no-roomba
    """
    print(_c("\n  R-7 Voice Chat Mode  (no hardware)\n", "cyan"))

    personality = Personality()
    ai_client   = OllamaClient()

    vc = VoiceChatManager(
        vosk_model_path = args.vosk_model,
        tts_rate        = 155,
        ai_client       = ai_client,
        personality     = personality,
        use_wake_word   = False,
    )

    if not vc.init():
        return 1

    vc.run_interactive(continuous=args.continuous)
    return 0


# ─── Argument parsing ─────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description  = "R-7 Droid — Roomba 650 AI droid",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Examples:\n"
            "  python main.py\n"
            "  python main.py --no-vision\n"
            "  python main.py --port /dev/ttyUSB0 --debug\n"
            "  python main.py --voice --no-roomba          # voice chat, no hardware\n"
            "  python main.py --voice --no-roomba --continuous\n"
            "  python main.py --voice                      # voice + Roomba hardware\n"
            "\nFirst-time voice setup:\n"
            "  bash scripts/download_vosk_model.sh\n"
            "  pip install vosk sounddevice pyttsx3\n"
            "\nSubsystem tests:\n"
            "  python roomba/roomba_test.py    (serial/movement testing)\n"
            "  python commands/command_console.py  (full interactive control)\n"
            "  python diagnostics/check_all.py     (system health check)\n"
        )
    )
    parser.add_argument("--port",         default=None,  help="Serial port (default: auto-detect)")
    parser.add_argument("--no-vision",    action="store_true", help="Disable camera/vision")
    parser.add_argument("--no-ai",        action="store_true", help="Disable Ollama AI")
    parser.add_argument("--no-behaviour", action="store_true", help="No autonomous movement")
    parser.add_argument("--debug",        action="store_true", help="Verbose debug logging")
    # ── Voice options ─────────────────────────────────────────────────────
    parser.add_argument(
        "--voice", action="store_true",
        help="Enable voice I/O (Vosk STT + pyttsx3 TTS)",
    )
    parser.add_argument(
        "--no-roomba", action="store_true",
        help="Skip Roomba hardware — run voice chat / AI only",
    )
    parser.add_argument(
        "--continuous", action="store_true",
        help="[voice] Always-listening mode — no Enter key needed (implies --no-roomba)",
    )
    parser.add_argument(
        "--vosk-model",
        default="models/vosk-model-small-en-us",
        metavar="PATH",
        help="[voice] Path to Vosk model directory (default: models/vosk-model-small-en-us)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    parsed = _parse_args()
    if parsed.debug:
        set_global_level("DEBUG")
    sys.exit(main(parsed))
