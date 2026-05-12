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

    # Minimum RMS energy a chunk must have before being sent to Vosk.
    # Prevents hallucinations from silence and stops monitor/loopback
    # sources (PulseAudio/PipeWire) being mistaken for real microphone input.
    # Range: 0-32768 (16-bit audio).  200 = very quiet room threshold.
    # Raise this if you're still getting false triggers in a noisy environment.
    SILENCE_THRESHOLD = 200

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

    # ─── One-shot synchronous listen ─────────────────────────────────────────

    def listen_once(self, timeout: float = 8.0) -> "str | None":
        """
        Synchronously listen for one complete utterance and return the text.

        • Does NOT require start() to have been called.
        • Does NOT apply wake-word filtering — the raw transcript is returned.
        • Returns recognised text (lowercase) or None on silence / timeout.

        Parameters
        ----------
        timeout : seconds to wait before giving up (default 8 s)
        """
        if self._engine_name == "vosk":
            return self._listen_once_vosk(timeout)
        elif self._engine_name == "google":
            return self._listen_once_google(timeout)
        log.error("listen_once: unsupported engine '%s'", self._engine_name)
        return None

    def _listen_once_vosk(self, timeout: float) -> "str | None":
        """One-shot Vosk listener — opens mic, captures one utterance, closes."""
        import json
        import queue as _queue
        import time

        try:
            from vosk import KaldiRecognizer
            import sounddevice as sd
        except ImportError:
            log.error("vosk/sounddevice not installed — pip install vosk sounddevice")
            return None

        # Lazy-init the model if needed (doesn't require start() to have run)
        if self._model is None:
            if not self._init_vosk():
                return None

        rec      = KaldiRecognizer(self._model, 16_000)
        audio_q: _queue.Queue = _queue.Queue(maxsize=200)  # ~12 s of audio at 8k blocks
        deadline = time.time() + timeout

        def _cb(indata, frames, time_info, status):
            if status:
                log.debug("Audio callback status: %s", status)
            try:
                audio_q.put_nowait(bytes(indata))
            except _queue.Full:
                pass  # drop oldest-ish data rather than blocking the audio thread

        try:
            with sd.RawInputStream(
                samplerate=16_000,
                blocksize=8_000,
                dtype="int16",
                channels=1,
                callback=_cb,
            ):
                while time.time() < deadline:
                    try:
                        data = audio_q.get(timeout=0.3)
                    except _queue.Empty:
                        continue

                    try:
                        if rec.AcceptWaveform(data):
                            result = json.loads(rec.Result())
                            text   = result.get("text", "").strip().lower()
                            if text:
                                return text
                            # Silence frame — recogniser reset, keep listening
                    except Exception as e:
                        log.warning("Vosk AcceptWaveform error: %s", e)
                        continue

        except Exception as e:
            log.error("listen_once audio stream error: %s", e)
            return None

        # Timeout reached — grab any partial text the recogniser has accumulated
        try:
            final = json.loads(rec.FinalResult()).get("text", "").strip().lower()
            return final if final else None
        except Exception:
            return None

    def _listen_once_google(self, timeout: float) -> "str | None":
        """One-shot Google STT listener."""
        try:
            import speech_recognition as sr
        except ImportError:
            log.error("speech_recognition not installed — pip install SpeechRecognition pyaudio")
            return None

        recogniser = sr.Recognizer()
        mic        = sr.Microphone()
        try:
            with mic as source:
                recogniser.adjust_for_ambient_noise(source, duration=0.5)
                audio = recogniser.listen(
                    source, timeout=timeout, phrase_time_limit=10.0
                )
            return recogniser.recognize_google(audio).lower()
        except Exception as e:
            log.debug("listen_once google: %s", e)
            return None

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
        """Initialise Vosk offline STT.  Safe to call multiple times."""
        # If already loaded, just refresh the KaldiRecognizer (cheap)
        if self._model is not None:
            try:
                from vosk import KaldiRecognizer
                self._recogniser = KaldiRecognizer(self._model, 16000)
                log.debug("Vosk KaldiRecognizer refreshed (model already loaded)")
                return True
            except Exception as e:
                log.error("Vosk KaldiRecognizer refresh failed: %s", e)
                return False

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

            log.info("Loading Vosk model from %s …", self._vosk_path)
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
        except Exception as e:
            log.error("Vosk init failed: %s", e)
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

    @staticmethod
    def _rms(data: bytes) -> float:
        """Return the RMS amplitude of a 16-bit PCM byte buffer."""
        import array as _array
        import math as _math
        samples = _array.array("h", data)
        if not samples:
            return 0.0
        return _math.sqrt(sum(s * s for s in samples) / len(samples))

    def _listen_vosk(self) -> None:
        """Vosk streaming microphone loop."""
        import sounddevice as sd
        import json

        log.debug("Vosk listen loop started")
        # blocksize controls how many frames are buffered per callback tick.
        # We read the same size so each stream.read() call drains exactly one
        # block — giving ~500 ms chunks at 16 kHz which Vosk handles well.
        BLOCK = 8000
        # Interrupt is only fired once per utterance start (first partial that
        # has non-empty text) to avoid hammering the TTS interrupt on every frame.
        _interrupt_fired = False

        # Log which device we're actually recording from so it's obvious
        # in the logs if the system has fallen back to a built-in / monitor source.
        try:
            dev = sd.query_devices(kind="input")
            log.info("STT using input device: '%s'", dev.get("name", "unknown"))
        except Exception:
            pass

        try:
            with sd.RawInputStream(
                samplerate=16000,
                blocksize=BLOCK,
                dtype="int16",
                channels=1,
            ) as stream:
                while self._running:
                    try:
                        data, overflowed = stream.read(BLOCK)
                        if overflowed:
                            log.debug("Audio buffer overflowed — some audio lost")
                    except Exception as e:
                        log.warning("Audio read error: %s — retrying", e)
                        import time as _t; _t.sleep(0.1)
                        continue

                    # ── Energy gate — skip silence / monitor source noise ──
                    raw = bytes(data)
                    if self._rms(raw) < self.SILENCE_THRESHOLD:
                        continue

                    try:
                        if self._recogniser.AcceptWaveform(raw):
                            result = json.loads(self._recogniser.Result())
                            text   = result.get("text", "").strip().lower()
                            _interrupt_fired = False   # reset for next utterance
                            if text:
                                log.debug("Vosk heard: %s", text)
                                self._process_text(text)
                        else:
                            # Partial result — fire interrupt ONCE at the start
                            # of an utterance so TTS stops immediately, but not
                            # on every frame (avoids a flood of interrupt calls).
                            if not _interrupt_fired:
                                partial = json.loads(self._recogniser.PartialResult())
                                if partial.get("partial", ""):
                                    _interrupt_fired = True
                                    if self._interrupt_callback:
                                        self._interrupt_callback()
                    except Exception as e:
                        log.warning("Vosk recognition error: %s", e)
                        continue
        except Exception as e:
            log.error("Vosk listen loop failed: %s", e, exc_info=True)

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
