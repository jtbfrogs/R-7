"""
ai/voice_chat.py
─────────────────
VoiceChatManager — integrates Vosk STT + pyttsx3 TTS + OllamaClient
into R-7's voice loop.

Used by main.py when --voice is passed.

Two modes
──────────
  interactive  Blocking foreground loop — ideal for voice-only sessions
               (no Roomba hardware required).  Supports push-to-talk
               (default) or continuous always-listening (--continuous).

  background   Daemon thread alongside the Roomba — always listening,
               fires the AI callback whenever a voice command is heard.

Quick-start (from main.py)
──────────────────────────
  # interactive voice session (no hardware needed):
  python main.py --voice --no-roomba

  # continuous listening (no Enter key):
  python main.py --voice --no-roomba --continuous

  # voice + Roomba hardware (background listener):
  python main.py --voice
"""

import threading
from pathlib import Path
from typing import Optional, Callable

from utilities.logger import get_logger

log = get_logger(__name__)

_EXIT_WORDS = {"quit", "exit", "q", "goodbye", "bye"}


# ─────────────────────────────────────────────────────────────────────────────

class VoiceChatManager:
    """
    Ties STTManager + TTSManager + OllamaClient into a complete voice session.

    Parameters
    ----------
    vosk_model_path : path to the downloaded Vosk model directory
                      (default: "models/vosk-model-small-en-us")
    tts_rate        : TTS speaking speed in words-per-minute (default: 155)
    tts_voice_id    : pyttsx3 voice ID  — "" = auto-select best English voice
    ai_client       : OllamaClient instance; created internally if None
    personality     : Personality instance for fallback phrases; optional
    use_wake_word   : if True, background mode only triggers after
                      "hey r-seven" is spoken (same as full hardware mode)
    """

    def __init__(
        self,
        vosk_model_path: str   = "models/vosk-model-small-en-us",
        tts_rate:        int   = 155,
        tts_voice_id:    str   = "",
        ai_client               = None,
        personality             = None,
        use_wake_word:   bool  = False,
    ):
        self._vosk_model_path = vosk_model_path
        self._tts_rate        = tts_rate
        self._tts_voice_id    = tts_voice_id
        self._use_wake_word   = use_wake_word

        self._ai_client  = ai_client
        self._personality = personality

        self._stt = None          # STTManager  (created in init())
        self._tts = None          # TTSManager  (created in init())
        self._running = False

    # ─── Dependency + model checks ────────────────────────────────────────────

    @staticmethod
    def check_dependencies() -> bool:
        """
        Verify that vosk, sounddevice, and pyttsx3 are installed.
        Logs a clear message for each missing package.
        Returns True only if ALL three are present.
        """
        missing = []
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            missing.append(
                "sounddevice  →  pip install sounddevice\n"
                "               (macOS: brew install portaudio first)"
            )
        try:
            from vosk import Model  # noqa: F401
        except ImportError:
            missing.append("vosk         →  pip install vosk")
        try:
            import pyttsx3  # noqa: F401
        except ImportError:
            missing.append(
                "pyttsx3      →  pip install pyttsx3\n"
                "               (Linux: sudo apt install espeak-ng)"
            )

        if missing:
            log.error(
                "Missing voice dependencies — install them and retry:\n  %s",
                "\n  ".join(missing),
            )
            print("\n✗  Missing voice dependencies:\n")
            for m in missing:
                print(f"    {m}")
            print()
            return False
        return True

    def check_model(self) -> bool:
        """
        Verify the Vosk model directory exists.
        Prints download instructions if it is missing.
        """
        p = Path(self._vosk_model_path)
        if not p.is_dir():
            msg = (
                f"\n✗  Vosk model not found at: {self._vosk_model_path}\n\n"
                "   Download it (one-time, ~40 MB):\n"
                "     bash scripts/download_vosk_model.sh\n\n"
                "   Or manually:\n"
                "     mkdir -p models && cd models\n"
                "     wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip\n"
                "     unzip vosk-model-small-en-us-0.15.zip\n"
                "     mv vosk-model-small-en-us-0.15 vosk-model-small-en-us\n"
            )
            log.error("Vosk model not found at: %s", self._vosk_model_path)
            print(msg)
            return False
        return True

    # ─── Init ─────────────────────────────────────────────────────────────────

    def init(self) -> bool:
        """
        Initialise the STT and TTS engines.  Must be called before
        run_interactive() or start_background().

        Returns True on success, False if any subsystem fails.
        """
        if not self.check_dependencies():
            return False
        if not self.check_model():
            return False

        from config.config_loader import get_config
        cfg = get_config()

        # ── STT (Vosk) ────────────────────────────────────────────────────
        cfg["audio"]["stt_engine"]          = "vosk"
        cfg["audio"]["vosk_model_path"]     = self._vosk_model_path
        cfg["audio"]["voice_input_enabled"] = True
        # Disable wake word for interactive mode (background can keep it)
        if not self._use_wake_word:
            cfg["audio"]["wake_word"] = ""

        from audio.stt_manager import STTManager
        self._stt = STTManager()

        print("Initialising STT (Vosk)…", end=" ", flush=True)
        if not self._stt._init_vosk():
            log.error("Vosk STT failed to initialise")
            return False
        print("ready.")

        # ── TTS (pyttsx3) ─────────────────────────────────────────────────
        cfg["audio"]["tts_engine"]   = "pyttsx3"
        cfg["audio"]["tts_rate_wpm"] = self._tts_rate
        if self._tts_voice_id:
            cfg["audio"]["tts_voice_id"] = self._tts_voice_id

        from audio.tts_manager import TTSManager
        self._tts = TTSManager()

        print("Initialising TTS (pyttsx3)…", end=" ", flush=True)
        if not self._tts._init_engine():
            log.error("TTS engine failed to initialise")
            return False

        voice_label = "default"
        if self._tts._engine:
            v = self._tts._engine.getProperty("voice") or ""
            voice_label = v.split(".")[-1] if v else "default"
        print(f"ready ({voice_label}).\n")

        # ── AI client (lazy creation) ─────────────────────────────────────
        if self._ai_client is None:
            from ai.ollama_client import OllamaClient
            self._ai_client = OllamaClient()

        log.info(
            "VoiceChatManager ready — model=%s  tts_rate=%d",
            self._vosk_model_path, self._tts_rate,
        )
        return True

    # ─── Internal helpers ──────────────────────────────────────────────────────

    def speak(self, text: str, block: bool = True) -> None:
        """Speak text via TTS.  block=True waits until speech is finished."""
        if not self._tts or not text.strip():
            return
        if block:
            self._tts.speak_sync(text)
        else:
            self._tts.speak(text)

    def _get_ai_response(self, user_input: str, context: str = "") -> str:
        """Ask the AI and return a spoken response string."""
        if self._ai_client and self._ai_client.is_available():
            reply = self._ai_client.ask(user_input, context=context or None)
            if reply:
                return reply
        # Fallback to personality phrase or generic reply
        if self._personality:
            return self._personality.react("confused")
        return "Hmm, I am not sure about that."

    # ─── Interactive (foreground) mode ────────────────────────────────────────

    def run_interactive(self, continuous: bool = False, context: str = "") -> None:
        """
        Blocking voice chat loop — run in the main thread for voice-only mode.

        Parameters
        ----------
        continuous : True = always listening, no Enter key needed.
                     False (default) = push-to-talk, press Enter before speaking.
        context    : optional string injected into every AI prompt as extra context
                     e.g. "I am a small robot droid"
        """
        if self._tts is None or self._stt is None:
            log.error("VoiceChatManager.run_interactive(): call init() first")
            return

        print()
        print("══════════════════════════════════════════")
        print("  R-7 Voice Chat")
        print("══════════════════════════════════════════")
        print(f"  Vosk model : {Path(self._vosk_model_path).name}")
        print(f"  Listen mode: {'continuous' if continuous else 'push-to-talk (Enter)'}")
        if context:
            print(f"  Context    : {context}")
        print()
        print("  Say 'quit' or press Ctrl-C to exit.")
        print("══════════════════════════════════════════\n")

        # Verify AI
        if self._ai_client and self._ai_client.is_available():
            print(f"✓ Ollama ready  ({self._ai_client._model})\n")
        else:
            print("⚠  Ollama not available — falling back to personality phrases.\n")

        self.speak("R-7 online. Hello!")
        self._running = True

        try:
            while self._running:
                # Push-to-talk gate
                if not continuous:
                    try:
                        input("[ Press Enter to speak, Ctrl-C to quit ]\n")
                    except EOFError:
                        break

                print("🎤  Listening…  (speak now)")
                user_input = self._stt.listen_once(timeout=8.0)

                if not user_input:
                    print("  (nothing heard — try again)\n")
                    continue

                print(f"\nYou: {user_input}")

                if user_input.lower().strip() in _EXIT_WORDS:
                    self.speak("Goodbye!")
                    break

                print("R-7: (thinking…)")
                response = self._get_ai_response(user_input, context=context)
                print(f"R-7 💬  {response}\n")
                self.speak(response)

        except KeyboardInterrupt:
            print("\nBye!")
            self.speak("Bye!")
        finally:
            self._running = False

    # ─── Background (hardware) mode ───────────────────────────────────────────

    def start_background(
        self,
        tts_manager               = None,
        interrupt_callback: Optional[Callable] = None,
    ) -> bool:
        """
        Start a background STT listener thread alongside running Roomba hardware.

        Speech is recognised continuously; when a command is detected the AI
        generates a reply and TTS speaks it without blocking the main loop.

        Parameters
        ----------
        tts_manager        : existing TTSManager already started by main.py
                             (avoids double-initialising the TTS engine)
        interrupt_callback : called the instant ANY speech is detected
                             (used to stop ongoing TTS mid-sentence)

        Returns True on success.
        """
        if self._stt is None:
            log.error("VoiceChatManager.start_background(): call init() first")
            return False

        # Re-use the TTS from main.py if provided
        if tts_manager is not None:
            self._tts = tts_manager

        if interrupt_callback:
            self._stt.set_interrupt_callback(interrupt_callback)

        def _on_voice_command(text: str) -> None:
            log.info("Voice command heard: %s", text)
            response = self._get_ai_response(text)
            log.info("Voice response: %s", response)
            self.speak(response, block=False)

        self._stt.set_callback(_on_voice_command)

        # Force-enable the manager (it checks the config flag at start())
        from config.config_loader import get_config
        cfg = get_config()
        cfg["audio"]["voice_input_enabled"] = True
        self._stt._enabled = True

        if not self._stt.start():
            log.error("STT background start failed")
            return False

        log.info(
            "VoiceChatManager background listening started (wake_word=%s)",
            repr(self._stt._wake_word or "(none)"),
        )
        return True

    def stop(self) -> None:
        """Stop the STT thread (call during shutdown)."""
        self._running = False
        if self._stt:
            self._stt.stop()
        log.info("VoiceChatManager stopped")
