"""
ai/personality.py
──────────────────
The droid's personality engine.

Responsibilities
────────────────
  • Store all personality phrases from config
  • Apply speech quirks (stutters, pauses, tone)
  • Choose random situational responses
  • Enforce response length limits
  • Track cooldown timers so the droid doesn't talk constantly

The personality is entirely configurable via default_config.yaml.
Changing the feel of the droid = editing YAML, not code.

Personality inspiration
────────────────────────
  BMO (Adventure Time)  — friendly, slightly naive, expressive
  D-O (Star Wars IX)    — anxious, short phrases, eager to please
  R2-D2                 — reactive to environment, beeps mixed with speech

Speech style rules
───────────────────
  • Short.  Never more than ~20 words.
  • React to the environment.
  • Occasional stutter on first word (b-b-but, h-hi, etc.)
  • Pause fillers: "Um.", "Hmm.", "..."
  • Never interrupt itself — if already speaking, don't queue more.
  • Cooldown between reactions so it's not annoying.
"""

import random
import time
import threading
from typing import Optional
from utilities.logger import get_logger
from utilities.helpers import truncate_words, weighted_choice
from utilities.constants import AI_MAX_RESPONSE_WORDS, AI_COOLDOWN_SEC
from config.config_loader import get_config

log = get_logger(__name__)


# ─── Stutter helper ──────────────────────────────────────────────────────────

def _apply_stutter(text: str, stutter_chance: float) -> str:
    """
    Occasionally repeat the first syllable of the first word.
    E.g. "Hello" → "H-hello"  or  "But" → "B-but"

    The effect is subtle — only triggered if random() < stutter_chance.
    """
    if stutter_chance <= 0 or random.random() > stutter_chance:
        return text

    words = text.split()
    if not words:
        return text

    first = words[0]
    if len(first) < 2:
        return text   # too short to stutter

    # Take the first letter + hyphen + lowercased full word
    stuttered = f"{first[0]}-{first.lower()}"
    words[0]  = stuttered
    return " ".join(words)


class Personality:
    """
    Manages the droid's speech personality.

    Usage
    ─────
        p = Personality()

        # Respond to a situation
        phrase = p.react("person_found")
        print(phrase)   # → "Oh! There you are."

        # Pass AI-generated text through the personality filter
        filtered = p.filter_ai_response("I detected a human and I am very excited about it!")
        print(filtered)  # → "I detected a human. Exciting!"  (truncated + quirked)

        # Check cooldown before speaking
        if p.can_speak():
            speak(phrase)
            p.mark_spoke()
    """

    def __init__(self):
        cfg = get_config()
        self._p_cfg    = cfg.get("personality", {})
        self._ai_cfg   = cfg.get("ai", {})

        self.name           = self._p_cfg.get("name", "R-7")
        self._stutter_chance = self._p_cfg.get("stutter_chance", 0.15)
        self._max_words     = self._ai_cfg.get("max_response_words", AI_MAX_RESPONSE_WORDS)
        self._cooldown_sec  = self._ai_cfg.get("response_cooldown_sec", AI_COOLDOWN_SEC)

        # Phrase bank from config
        self._phrases: dict[str, list[str]] = self._p_cfg.get("phrases", {})

        # Cooldown tracking — lock prevents multiple threads passing can_speak()
        # simultaneously before any of them call mark_spoke().
        self._last_spoke: float = 0.0
        self._speak_lock = threading.Lock()

        log.debug("Personality '%s' loaded (stutter=%.0f%%, max_words=%d, cooldown=%.1fs)",
                  self.name, self._stutter_chance * 100, self._max_words, self._cooldown_sec)

    # ─── Phrase selection ────────────────────────────────────────────────────

    def react(self, situation: str) -> str:
        """
        Return a random phrase for a given situation.

        Parameters
        ----------
        situation : key matching a phrases section in config, e.g.:
                    "startup", "person_found", "person_lost",
                    "obstacle_detected", "roaming", "docking",
                    "confused", "happy"

        Returns
        -------
        A phrase string, with stutter possibly applied.
        Falls back to a generic "Hmm?" if the situation isn't in config.
        """
        options = self._phrases.get(situation, ["Hmm?"])
        phrase  = random.choice(options)
        phrase  = _apply_stutter(phrase, self._stutter_chance)
        log.debug("Personality react [%s]: %s", situation, phrase)
        return phrase

    def filter_ai_response(self, text: str) -> str:
        """
        Run a raw AI model response through the personality filter:
          1. Truncate to max word count
          2. Maybe apply stutter to first word
          3. Clean up whitespace

        Parameters
        ----------
        text : raw text from Ollama

        Returns
        -------
        Filtered, droid-appropriate response string.
        """
        if not text or not text.strip():
            return self.react("confused")

        # Clean up
        cleaned = text.strip()

        # Truncate
        truncated = truncate_words(cleaned, self._max_words)

        # Apply stutter
        final = _apply_stutter(truncated, self._stutter_chance * 0.5)   # less stutter on AI text

        log.debug("AI response filtered: [%d words] %s", len(final.split()), final)
        return final

    def greeting(self) -> str:
        """Return a startup greeting."""
        return self.react("startup")

    def farewell(self) -> str:
        """Return a shutdown phrase."""
        return self.react("docking")

    # ─── Cooldown management ─────────────────────────────────────────────────

    def can_speak(self) -> bool:
        """
        Return True if enough time has passed since the last speech event,
        AND atomically mark that we intend to speak (so concurrent threads
        don't all pass the check at the same time).

        Pattern: if personality.can_speak(): ... personality.mark_spoke()
        is replaced by a single atomic call — use acquire_speak_slot() instead
        when calling from threads.
        """
        elapsed = time.time() - self._last_spoke
        return elapsed >= self._cooldown_sec

    def acquire_speak_slot(self) -> bool:
        """
        Thread-safe version: returns True AND stamps _last_spoke atomically.
        Use this from background threads so concurrent callers don't both
        pass the cooldown check before either has updated the timestamp.
        """
        with self._speak_lock:
            if time.time() - self._last_spoke >= self._cooldown_sec:
                self._last_spoke = time.time()
                return True
            return False

    def mark_spoke(self) -> None:
        """Manually stamp the cooldown timer (use after speaking)."""
        with self._speak_lock:
            self._last_spoke = time.time()

    def time_until_can_speak(self) -> float:
        """Returns 0.0 if ready, or the remaining cooldown seconds."""
        elapsed = time.time() - self._last_spoke
        remaining = self._cooldown_sec - elapsed
        return max(0.0, remaining)

    # ─── Quirk helpers ───────────────────────────────────────────────────────

    def add_pause_filler(self, text: str) -> str:
        """
        Occasionally prefix text with a filler like "Um." or "Hmm…".
        Very low probability — should feel natural, not constant.
        """
        fillers = ["Um. ", "Hmm. ", "...  ", "Oh. ", ""]
        weights = [0.1,   0.1,    0.05,   0.05,  0.7 ]  # 70% chance: no filler
        filler  = weighted_choice(fillers, weights)
        return filler + text if filler else text
