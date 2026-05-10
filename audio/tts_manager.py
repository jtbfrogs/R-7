"""
audio/tts_manager.py
─────────────────────
Text-to-Speech manager for the droid's voice.

Backend support
────────────────
  pyttsx3  — Default. Works out of the box on Linux (uses espeak/festival).
             Fast to start. Voice quality is basic but functional.
             No internet required.

  piper    — Recommended upgrade. Fast, offline, very natural voice.
             Install: pip install piper-tts
             Download a voice: https://github.com/rhasspy/piper/releases
             Config: set tts_engine: "piper" in local_config.yaml

The manager uses a SPEECH QUEUE + background thread so:
  • Speech never blocks the main loop
  • Interruption works (call interrupt())
  • The droid can queue multiple short phrases

INTERRUPTION
────────────
When the microphone hears input, call interrupt().
This immediately stops current speech and clears the queue.
"""

import queue
import threading
import time
from typing import Optional

from utilities.logger import get_logger
from utilities.constants import TTS_RATE_WPM, TTS_VOLUME, SPEECH_QUEUE_MAXLEN
from config.config_loader import get_config

log = get_logger(__name__)


class TTSManager:
    """
    Non-blocking text-to-speech with interruption support.

    Usage
    ─────
        tts = TTSManager()
        tts.start()
        tts.speak("Hello! I am R-7.")
        tts.speak("Person detected.")
        # Both are queued and spoken in order
        tts.interrupt()   # stop mid-sentence if needed
        tts.stop()
    """

    def __init__(self):
        cfg           = get_config()["audio"]
        self._engine_name = cfg.get("tts_engine", "pyttsx3")
        self._rate        = cfg.get("tts_rate_wpm", TTS_RATE_WPM)
        self._volume      = cfg.get("tts_volume",   TTS_VOLUME)
        self._voice_id    = cfg.get("tts_voice_id", "")
        self._enabled     = cfg.get("tts_enabled",  True)
        self._max_queue   = cfg.get("speech_queue_maxlen", SPEECH_QUEUE_MAXLEN)

        self._queue:   queue.Queue = queue.Queue(maxsize=self._max_queue)
        self._engine   = None
        self._thread:  Optional[threading.Thread] = None
        self._running  = False
        self._speaking = False
        self._interrupt_flag = threading.Event()

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Initialise TTS engine and start the speech queue thread."""
        if not self._enabled:
            log.info("TTS disabled in config — speech will be skipped")
            return True

        if not self._init_engine():
            return False

        self._running = True
        self._thread  = threading.Thread(
            target  = self._speech_loop,
            daemon  = True,
            name    = "TTSThread",
        )
        self._thread.start()
        log.info("TTS manager started (engine=%s, rate=%d wpm)", self._engine_name, self._rate)
        return True

    def stop(self) -> None:
        """Stop the speech thread and clean up."""
        self._running = False
        self._interrupt_flag.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        log.info("TTS manager stopped")

    def _init_engine(self) -> bool:
        """Initialise the configured TTS backend."""
        if self._engine_name == "pyttsx3":
            return self._init_pyttsx3()
        elif self._engine_name == "piper":
            return self._init_piper()
        else:
            log.error("Unknown TTS engine: '%s' — defaulting to pyttsx3", self._engine_name)
            return self._init_pyttsx3()

    def _init_pyttsx3(self) -> bool:
        try:
            import pyttsx3
            engine = pyttsx3.init()

            # ── Volume ──────────────────────────────────────────────────
            engine.setProperty("volume", self._volume)

            # ── Rate: default 165 wpm is too fast for espeak's robotic
            #    voice.  130 wpm is much more intelligible.  Config can
            #    still override this via tts_rate_wpm.
            rate = min(self._rate, 140)   # cap at 140 for clarity
            engine.setProperty("rate", rate)

            # ── Voice selection ──────────────────────────────────────────
            if self._voice_id:
                engine.setProperty("voice", self._voice_id)
            else:
                voices = engine.getProperty("voices") or []
                log.debug("Available TTS voices: %s", [v.id for v in voices])
                selected = self._pick_best_voice(voices)
                if selected:
                    engine.setProperty("voice", selected)
                    log.info("TTS voice selected: %s", selected)
                else:
                    log.info("Using default TTS voice")

            self._engine = engine
            log.info("pyttsx3 ready — rate=%d wpm  volume=%.1f", rate, self._volume)
            return True

        except ImportError:
            log.error(
                "pyttsx3 not installed.\n"
                "  Install : pip install pyttsx3\n"
                "  espeak  : sudo apt install espeak-ng\n"
                "  mbrola  : sudo apt install mbrola mbrola-us1 mbrola-us2"
            )
            return False
        except Exception as e:
            log.error("pyttsx3 init failed: %s", e)
            return False

    @staticmethod
    def _pick_best_voice(voices) -> str | None:
        """
        Choose the most intelligible English voice from the list available.

        Priority (best to worst):
          1. mbrola/us2 or mbrola/us1  — naturalish, male, clear
          2. mbrola/en1               — British male, decent
          3. espeak-ng en-us (variant m3 or m7)
          4. Any voice with "english" in the id
          5. None (fall back to system default)

        To list your available voices:
            python3 -c "import pyttsx3; e=pyttsx3.init(); [print(v.id) for v in e.getProperty('voices')]"

        To install mbrola voices (Pop!_OS / Ubuntu):
            sudo apt install espeak-ng mbrola mbrola-us1 mbrola-us2 mbrola-en1
        """
        voice_ids = [v.id for v in voices]

        # Preference list — first match wins
        preferences = [
            "mb-us2",   # mbrola US male 2  — clear, natural
            "mb-us1",   # mbrola US male 1
            "mb-en1",   # mbrola British male
            "en-us",    # espeak-ng en-us
            "english-us",
            "english",
        ]

        for pref in preferences:
            for vid in voice_ids:
                if pref in vid.lower():
                    return vid

        # Last resort: any voice containing "en"
        for vid in voice_ids:
            if "/en" in vid.lower() or "english" in vid.lower():
                return vid

        return None

    def _init_piper(self) -> bool:
        """Piper TTS — offline neural TTS, much better voice quality."""
        try:
            from piper.voice import PiperVoice
            import wave

            voice_path = get_config()["audio"].get("piper_model_path", "models/en_US-lessac-medium.onnx")
            self._piper_voice = PiperVoice.load(voice_path)
            self._engine_name = "piper"
            log.info("Piper TTS engine ready (model=%s)", voice_path)
            return True

        except ImportError:
            log.error(
                "Piper TTS not installed.\n"
                "  Install: pip install piper-tts\n"
                "  Download a voice model from: https://github.com/rhasspy/piper/releases\n"
                "  Falling back to pyttsx3..."
            )
            self._engine_name = "pyttsx3"
            return self._init_pyttsx3()
        except Exception as e:
            log.error("Piper init failed: %s — falling back to pyttsx3", e)
            self._engine_name = "pyttsx3"
            return self._init_pyttsx3()

    # ─── Public speech interface ─────────────────────────────────────────────

    def speak(self, text: str, priority: bool = False) -> None:
        """
        Queue a phrase for speaking.

        Parameters
        ----------
        text     : the text to speak
        priority : if True, clear the queue first (speak this ASAP)

        If the queue is full, the oldest item is dropped.
        """
        if not self._enabled or not text.strip():
            return

        if priority:
            self.interrupt()

        try:
            # If queue is full, drop the oldest item to make room
            if self._queue.full():
                try:
                    dropped = self._queue.get_nowait()
                    log.debug("Speech queue full — dropped: %s", dropped[:30])
                except queue.Empty:
                    pass

            self._queue.put_nowait(text)
            log.debug("Queued speech: %s", text[:60])

        except Exception as e:
            log.error("Failed to queue speech: %s", e)

    def interrupt(self) -> None:
        """
        Stop any current speech immediately and clear the queue.
        Called when microphone input is detected.
        """
        log.debug("Speech interrupted")
        self._interrupt_flag.set()
        # Drain the queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    @property
    def is_speaking(self) -> bool:
        """True if the droid is currently speaking."""
        return self._speaking

    # ─── Background speech loop ──────────────────────────────────────────────

    def _speech_loop(self) -> None:
        """Background thread — dequeues and speaks text items."""
        while self._running:
            try:
                text = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            self._interrupt_flag.clear()
            self._speaking = True
            log.debug("Speaking: %s", text[:80])

            try:
                self._say(text)
            except Exception as e:
                log.error("Speech error: %s", e)

            self._speaking = False

        log.debug("Speech loop ended")

    def _say(self, text: str) -> None:
        """Synthesise and play `text` using the configured engine."""
        if self._engine_name == "pyttsx3" and self._engine:
            self._engine.say(text)
            self._engine.runAndWait()

        elif self._engine_name == "piper":
            import subprocess, tempfile, os
            # Piper writes audio to a wav file, then we play it
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name

            try:
                self._piper_voice.synthesize_to_file(text, wav_path)
                if not self._interrupt_flag.is_set():
                    subprocess.run(
                        ["aplay", wav_path],
                        check=False, capture_output=True,
                    )
            finally:
                os.unlink(wav_path)
