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
import time
from typing import Optional

try:
    import httpx   # faster and cleaner than requests
except ImportError:
    try:
        import requests as httpx   # type: ignore  # fallback
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
# This shapes the AI's voice.  Keep it SHORT — small models have tiny context.
_SYSTEM_PROMPT = """You are R-7, a small friendly robot droid.
Rules:
- Reply in 1-2 short sentences MAXIMUM.
- Never more than 15 words total.
- Be friendly, slightly awkward, curious.
- React to what the user or context tells you.
- Use simple words.
- No long explanations."""


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

    # ─── Availability ─────────────────────────────────────────────────────────

    def is_available(self, force_check: bool = False) -> bool:
        """
        Check whether Ollama is running and the configured model is loaded.

        Result is cached after the first check.
        Set force_check=True to re-test (e.g. after starting Ollama manually).
        """
        if not self._enabled:
            return False

        if self._available is not None and not force_check:
            return self._available

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
                log.info("Ollama available — model '%s' loaded", self._model)
                self._available = True
            else:
                log.warning(
                    "Ollama running but model '%s' not found.\n"
                    "  Available models: %s\n"
                    "  Install with: ollama pull %s",
                    self._model, models or "(none)", self._model
                )
                self._available = False

        except Exception as e:
            log.warning(
                "Ollama not available at %s: %s\n"
                "  Is Ollama running?  Start it with: ollama serve",
                self._host, e
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

            log.debug("Ollama responded in %.1fs: %s", elapsed, raw_text[:80])

            # Truncate to keep the droid from rambling
            trimmed = truncate_words(raw_text, self._max_words)
            return trimmed

        except httpx.TimeoutException:
            log.warning("Ollama request timed out after %.1fs", self._timeout)
            return None
        except httpx.HTTPStatusError as e:
            log.error("Ollama HTTP error: %s", e)
            return None
        except Exception as e:
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
