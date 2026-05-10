"""
audio/stt_manager.py
──────────────────────
Speech-to-Text (microphone input) manager.

Two backend options
────────────────────
  vosk    — Fully offline, runs on CPU, good accuracy for short phrases.
            Download a small English model (~40MB) from:
              https://alphacephei.com/vosk/models
              → vosk-model-small-en-us-0.15

  google  — Online, better accuracy, requires internet.
            Uses the SpeechRecognition library's Google backend.

Wake word
──────────
Before full STT, a lightweight wake-word check runs.
If the phrase doesn't start with "hey r-seven", it's ignored.
This prevents the droid from reacting to every noise.

Interruption
─────────────
When the microphone hears ANY speech, call tts_manager.interrupt()
to stop the droid mid-sentence.  Microphone always wins.
"""

import queue
import threading
import time
from typing import Optional, Callable

from utilities.logger import get_logger
from utilities.constants import WAKE_WORD
from config.config_loader import get_config

log = get_logger(__name__)


class STTManager:
    """
    Listens for speech and triggers callbacks.

    Usage
    ─────
        def on_heard(text: str):
            print(f"Heard: {text}")

        stt = STTManager()
        stt.set_callback(on_heard)
        stt.start()
        # ... runs in background ...
        stt.stop()
    """

    def __init__(self):
        cfg = get_config()["audio"]
        self._engine_name   = cfg.get("stt_engine", "vosk")
        self._vosk_path     = cfg.get("vosk_model_path", "models/vosk-model-small-en-us")
        self._wake_word     = cfg.get("wake_word", WAKE_WORD).lower()
        self._enabled       = cfg.get("voice_input_enabled", False)

        self._callback: Optional[Callable[[str], None]] = None
        self._interrupt_callback: Optional[Callable[[], None]] = None
        # Optional callback fired whenever ANY speech fragment is heard.
        # Used by the command console to print raw heard text to the terminal.
        self._on_heard_callback: Optional[Callable[[str], None]] = None
        self._thread:   Optional[threading.Thread] = None
        self._running   = False
        self._model     = None
        self._recogniser = None

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    def set_callback(self, callback: Callable[[str], None]) -> None:
        """Set function to call when speech is recognised (after wake word)."""
        self._callback = callback

    def set_interrupt_callback(self, callback: Callable[[], None]) -> None:
        """Set function to call the INSTANT any speech is detected (for TTS interrupt)."""
        self._interrupt_callback = callback

    def set_heard_callback(self, callback: Callable[[str], None]) -> None:
        """
        Register a function called with every recognised speech fragment.
        The command console uses this to print heard text to the terminal.
        Fires for ALL speech, not just wake-word-matched commands.
        """
        self._on_heard_callback = callback

    def start(self) -> bool:
        """Start listening in the background."""
        if not self._enabled:
            log.info("Voice input disabled in config — set voice_input_enabled: true to enable")
            return False

        if not self._init_engine():
            log.error("STT engine failed to initialise — voice input disabled")
            return False

        self._running = True
        self._thread  = threading.Thread(
            target  = self._listen_loop,
            daemon  = True,
            name    = "STTThread",
        )
        self._thread.start()
        log.info("STT manager started (engine=%s, wake_word='%s')", self._engine_name, self._wake_word)
        return True

    def stop(self) -> None:
        """Stop the listen thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        log.info("STT manager stopped")

    def _init_engine(self) -> bool:
        """Initialise the configured STT backend."""
        if self._engine_name == "vosk":
            return self._init_vosk()
        elif self._engine_name == "google":
            return self._init_google()
        else:
            log.error("Unknown STT engine: %s", self._engine_name)
            return False

    def _init_vosk(self) -> bool:
        """Initialise Vosk offline STT."""
        try:
            from vosk import Model, KaldiRecognizer
            import sounddevice as sd
            import os

            if not os.path.isdir(self._vosk_path):
                log.error(
                    "Vosk model not found at: %s\n"
                    "  Download a model from: https://alphacephei.com/vosk/models\n"
                    "  Recommended: vosk-model-small-en-us-0.15 (~40 MB)\n"
                    "  Extract to: %s",
                    self._vosk_path, self._vosk_path
                )
                return False

            self._model = Model(self._vosk_path)
            self._recogniser = KaldiRecognizer(self._model, 16000)
            log.info("Vosk model loaded from %s", self._vosk_path)
            return True

        except ImportError as e:
            log.error(
                "Vosk STT dependencies missing: %s\n"
                "  Install: pip install vosk sounddevice",
                e
            )
            return False

    def _init_google(self) -> bool:
        """Initialise Google Web STT (requires internet)."""
        try:
            import speech_recognition as sr
            self._recogniser = sr.Recognizer()
            self._sr = sr
            log.info("Google STT engine ready")
            return True
        except ImportError:
            log.error("speech_recognition not installed: pip install SpeechRecognition pyaudio")
            return False

    # ─── Listening loops ─────────────────────────────────────────────────────

    def _listen_loop(self) -> None:
        """Dispatch to the correct listening loop for the engine."""
        if self._engine_name == "vosk":
            self._listen_vosk()
        elif self._engine_name == "google":
            self._listen_google()

    def _listen_vosk(self) -> None:
        """Vosk streaming microphone loop."""
        import sounddevice as sd
        import json

        log.debug("Vosk listen loop started")
        with sd.RawInputStream(
            samplerate=16000,
            blocksize=8000,
            dtype="int16",
            channels=1,
        ) as stream:
            while self._running:
                data, _ = stream.read(4000)
                if self._recogniser.AcceptWaveform(bytes(data)):
                    result = json.loads(self._recogniser.Result())
                    text   = result.get("text", "").strip().lower()
                    if text:
                        log.debug("Vosk heard: %s", text)
                        self._process_text(text)
                else:
                    # Partial result — check for any speech to trigger interrupt
                    partial = json.loads(self._recogniser.PartialResult())
                    if partial.get("partial", ""):
                        if self._interrupt_callback:
                            self._interrupt_callback()

    def _listen_google(self) -> None:
        """Google Web STT loop — listens in chunks."""
        sr = self._sr
        mic = sr.Microphone()

        log.debug("Google STT listen loop started")
        with mic as source:
            self._recogniser.adjust_for_ambient_noise(source)

        while self._running:
            try:
                with mic as source:
                    audio = self._recogniser.listen(source, timeout=2.0, phrase_time_limit=5.0)
                    if self._interrupt_callback:
                        self._interrupt_callback()

                text = self._recogniser.recognize_google(audio).lower()
                log.debug("Google STT heard: %s", text)
                self._process_text(text)

            except sr.WaitTimeoutError:
                pass   # silence — keep looping
            except sr.UnknownValueError:
                pass   # couldn't understand
            except Exception as e:
                log.warning("STT error: %s", e)
                time.sleep(0.5)

    def _process_text(self, text: str) -> None:
        """
        Check for wake word and dispatch to callback.
        Always fires interrupt callback immediately when speech detected.
        """
        # Fire interrupt on ANY detected speech (TTS should stop)
        if self._interrupt_callback:
            self._interrupt_callback()

        # Show everything heard in terminal (before wake-word filter)
        if self._on_heard_callback and text:
            try:
                self._on_heard_callback(text)
            except Exception:
                pass

        # Check wake word
        if self._wake_word and self._wake_word not in text:
            log.debug("Wake word '%s' not found in: '%s'", self._wake_word, text)
            return

        # Strip wake word prefix from the actual command
        command = text.replace(self._wake_word, "").strip()
        log.info("Voice command received: '%s'", command)

        if self._callback and command:
            self._callback(command)
