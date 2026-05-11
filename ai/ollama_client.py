"""
ai/ollama_client.py
────────────────────
Thin wrapper around the Ollama HTTP API.

Ollama runs as a local server at http://localhost:11434.
It serves language models (tinyllama, phi3:mini, etc.) via a REST API.

This client
────────────
  • Sends a prompt with droid-context to the model
  • Returns a short response string
  • Has timeout handling (so a slow model doesn't freeze the robot)
  • Falls back gracefully if Ollama is not running

The AI system is OPTIONAL.  If Ollama is not available, the droid
falls back to personality phrases only (which is fine for v1.0).

Installation
────────────
  curl -fsSL https://ollama.com/install.sh | sh
  ollama pull tinyllama        # ~670 MB
  ollama pull phi3:mini        # ~2.3 GB  (better quality)
  ollama serve                 # start the server (auto-starts on install)

Reference: https://github.com/ollama/ollama/blob/main/docs/api.md
"""

import json
import re
import time
from typing import Optional

try:
    import httpx   # faster and cleaner than requests
    _USING_HTTPX = True
except ImportError:
    try:
        import requests as httpx   # type: ignore  # fallback
        _USING_HTTPX = False
    except ImportError:
        raise ImportError(
            "httpx (or requests) required for AI.\n"
            "Install: pip install httpx"
        )

from utilities.logger import get_logger
from utilities.constants import OLLAMA_HOST, OLLAMA_DEFAULT_MODEL, OLLAMA_TIMEOUT_SEC, AI_MAX_RESPONSE_WORDS
from utilities.helpers import truncate_words
from config.config_loader import get_config

log = get_logger(__name__)


# ─── System prompt ────────────────────────────────────────────────────────────
# Kept extremely short and directive because small models (tinyllama, phi3:mini)
# ignore polite suggestions and need hard rules to stay on topic.
_SYSTEM_PROMPT = (
    "You are R-7, a tiny robot. "
    "RULES: Reply with ONE short sentence, max 8 words. "
    "NO parentheses. NO stage directions. NO 'User:' or 'Robot:' labels. "
    "NO roleplay. NO storytelling. Just speak as yourself. "
    "Be friendly and slightly awkward. "
    "Example good replies: 'Oh hi there!' / 'I found you!' / 'Hmm, okay.'"
)

# ─── Response sanitiser ────────────────────────────────────────────────────────
_STRIP_PATTERNS = [
    (re.compile(r"\([^)]*\)"),   ""),   # (stage directions)
    (re.compile(r"\[[^\]]*\]"),  ""),   # [bracketed notes]
    # Character labels anywhere in the text — no ^ anchor so mid-line hits too
    (re.compile(r"\b(User|Robot|AI|R-7|R7|Human|Assistant)\s*:\s*", re.I), ""),
    (re.compile(r"[*_`#]"),        ""),   # markdown
    (re.compile(r"\s{2,}"),       " "),  # collapse extra whitespace
]

def _sanitise(text: str) -> str:
    """Strip roleplay artifacts, stage directions, and character labels."""
    for pattern, replacement in _STRIP_PATTERNS:
        text = pattern.sub(replacement, text)
    text = text.strip()
    # Keep first sentence INCLUDING its terminal punctuation (.!?)
    # so "Oh! Hi." → "Oh!" not "Oh"
    m = re.search(r"[.!?]", text)
    if m and m.start() > 0:
        return text[: m.end()].strip()
    # No punctuation found — take up to first newline, or whole string
    return text.split("\n")[0].strip() or text


class OllamaClient:
    """
    Communicates with a locally running Ollama instance.

    Usage
    ─────
        ai = OllamaClient()
        if ai.is_available():
            response = ai.ask("Someone is waving at me. What should I say?")
            print(response)   # → "Oh! H-hi there!"
    """

    def __init__(self):
        cfg = get_config()["ai"]
        self._host     = cfg.get("host",    OLLAMA_HOST)
        self._model    = cfg.get("model",   OLLAMA_DEFAULT_MODEL)
        self._timeout  = cfg.get("timeout_sec", OLLAMA_TIMEOUT_SEC)
        self._max_words = cfg.get("max_response_words", AI_MAX_RESPONSE_WORDS)
        self._enabled  = cfg.get("enabled", True)

        self._available: Optional[bool] = None   # cached availability check
        self._last_check_time: float = 0.0        # when we last checked
        # Re-check availability this often when Ollama was unavailable.
        # Allows the droid to pick up Ollama if you start it after launch.
        self._recheck_interval: float = 30.0      # seconds

    # ─── Availability ─────────────────────────────────────────────────────────

    def is_available(self, force_check: bool = False) -> bool:
        """
        Check whether Ollama is running and the configured model is loaded.

        Result is cached after the first check.
        Set force_check=True to re-test (e.g. after starting Ollama manually).
        """
        if not self._enabled:
            return False

        now = time.time()
        if self._available is not None and not force_check:
            # If we previously confirmed it IS available, trust that result.
            if self._available:
                return True
            # If we previously got False, re-check after the recheck interval
            # so the droid recovers automatically if Ollama starts later.
            if now - self._last_check_time < self._recheck_interval:
                return False
            log.debug("Ollama recheck interval elapsed — retrying availability check")

        self._last_check_time = now

        try:
            # GET /api/tags  →  list of available models
            url  = f"{self._host}/api/tags"
            resp = httpx.get(url, timeout=3.0)
            resp.raise_for_status()

            data   = resp.json()
            models = [m["name"] for m in data.get("models", [])]

            # Check if our configured model is available
            # Model names can include tags like "tinyllama:latest"
            model_base = self._model.split(":")[0]
            found = any(m.startswith(model_base) for m in models)

            if found:
                log.info("Ollama available — model '%s' ready", self._model)
                self._available = True
            else:
                log.warning(
                    "Ollama is running but model '%s' is not loaded.\n"
                    "  Loaded models : %s\n"
                    "  Fix           : ollama pull %s\n"
                    "  Will retry in : %.0f seconds",
                    self._model,
                    models or "(none)",
                    self._model,
                    self._recheck_interval,
                )
                self._available = False

        except Exception as e:
            log.warning(
                "Ollama not available at %s — %s\n"
                "  Start it with : ollama serve\n"
                "  Will retry in : %.0f seconds",
                self._host, e, self._recheck_interval,
            )
            self._available = False

        return self._available

    # ─── Ask ──────────────────────────────────────────────────────────────────

    def ask(self, prompt: str, context: Optional[str] = None) -> Optional[str]:
        """
        Send a prompt to the AI model and return a short response.

        Parameters
        ----------
        prompt  : the user's message or a description of the situation
        context : optional extra context (e.g. "I can see a person on my left")

        Returns
        -------
        str  — the AI's response (already truncated to max_words)
        None — if Ollama is unavailable or times out
        """
        if not self.is_available():
            return None

        # Build the full prompt with optional context
        full_prompt = prompt
        if context:
            full_prompt = f"[Context: {context}]\n{prompt}"

        payload = {
            "model":  self._model,
            "prompt": full_prompt,
            "system": _SYSTEM_PROMPT,
            "stream": False,   # get the full response at once
            "options": {
                "temperature": 0.7,
                "num_predict": 60,   # token limit — keeps responses short
            },
        }

        start = time.time()
        try:
            url  = f"{self._host}/api/generate"
            resp = httpx.post(url, json=payload, timeout=self._timeout)
            resp.raise_for_status()

            data     = resp.json()
            raw_text = data.get("response", "").strip()
            elapsed  = time.time() - start

            # Sanitise first (strip roleplay/labels), then word-cap
            cleaned = _sanitise(raw_text)
            trimmed = truncate_words(cleaned, self._max_words)

            log.debug("Ollama %.1fs raw=%r  →  cleaned=%r", elapsed, raw_text[:60], trimmed)
            return trimmed

        except Exception as e:
            # httpx raises httpx.TimeoutException; requests raises
            # requests.exceptions.Timeout — catch both via the name.
            ename = type(e).__name__
            if "Timeout" in ename or "timeout" in ename.lower():
                log.warning("Ollama request timed out after %.1fs", self._timeout)
                return None
            # HTTP status errors (4xx / 5xx)
            if "StatusError" in ename or "HTTPError" in ename:
                log.error("Ollama HTTP error: %s", e)
                return None
            log.error("Ollama request failed: %s", e)
            self._available = None   # force re-check next time
            return None

    def ask_with_vision_context(
        self,
        situation: str,
        person_detected: bool,
        target_offset: float,
        extra: str = "",
    ) -> Optional[str]:
        """
        Convenience method that bundles vision state into a prompt.

        Parameters
        ----------
        situation      : what's happening e.g. "person is waving"
        person_detected: is a person visible?
        target_offset  : horizontal offset -1 to +1 (negative=left)
        extra          : any other context to include
        """
        context_parts = []
        if person_detected:
            direction = "left" if target_offset < -0.2 else "right" if target_offset > 0.2 else "centre"
            context_parts.append(f"Person visible, slightly to my {direction}")
        else:
            context_parts.append("No person visible")
        if extra:
            context_parts.append(extra)

        context = ". ".join(context_parts)
        return self.ask(situation, context)

    def get_model_info(self) -> dict:
        """Return info about the configured model."""
        return {
            "host":      self._host,
            "model":     self._model,
            "timeout":   self._timeout,
            "available": self._available,
            "enabled":   self._enabled,
        }
