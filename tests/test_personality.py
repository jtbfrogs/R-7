"""
tests/test_personality.py
──────────────────────────
Unit tests for the personality and AI response filtering.
No hardware required.

Run with: pytest tests/
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import pytest
from ai.personality import Personality, _apply_stutter
from utilities.helpers import truncate_words


class TestStutter:
    def test_no_stutter_at_zero_chance(self):
        # 0% chance = never stutter
        for _ in range(50):
            result = _apply_stutter("Hello there", 0.0)
            assert result == "Hello there"

    def test_always_stutter_at_one_chance(self):
        # 100% chance = always stutter
        for _ in range(10):
            result = _apply_stutter("Hello there", 1.0)
            assert result.startswith("H-")

    def test_stutter_preserves_rest_of_text(self):
        result = _apply_stutter("Hello world", 1.0)
        assert "world" in result

    def test_short_word_no_stutter(self):
        result = _apply_stutter("I am here", 1.0)
        # "I" is only 1 char — no stutter possible
        assert result == "I am here"


class TestPersonality:
    def test_react_returns_string(self):
        p = Personality()
        result = p.react("startup")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_react_unknown_situation_falls_back(self):
        p = Personality()
        result = p.react("nonexistent_situation_xyz")
        assert isinstance(result, str)

    def test_filter_truncates_long_response(self):
        p = Personality()
        long_text = " ".join(["word"] * 100)
        result = p.filter_ai_response(long_text)
        word_count = len(result.replace("...", "").split())
        assert word_count <= 25   # some tolerance for stutter addition

    def test_filter_empty_returns_fallback(self):
        p = Personality()
        result = p.filter_ai_response("")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_cooldown_starts_ready(self):
        p = Personality()
        assert p.can_speak() is True

    def test_cooldown_after_speaking(self):
        p = Personality()
        p.mark_spoke()
        # Should not be able to speak immediately
        # (unless cooldown_sec is 0, which it shouldn't be)
        if p._cooldown_sec > 0:
            assert p.can_speak() is False

    def test_cooldown_expires(self):
        p = Personality()
        p._cooldown_sec = 0.05   # very short for testing
        p.mark_spoke()
        time.sleep(0.1)
        assert p.can_speak() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
