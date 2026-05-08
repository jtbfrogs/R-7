"""
diagnostics/check_tts.py
─────────────────────────
Test TTS — the droid will speak a few phrases.

Usage
─────
    python diagnostics/check_tts.py
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def run() -> bool:
    print("\n  Testing TTS (pyttsx3)...")
    try:
        import pyttsx3
    except ImportError:
        print("  ✗  pyttsx3 not installed.  Run: pip install pyttsx3")
        print("     Also: sudo apt install espeak espeak-data libespeak1")
        return False

    try:
        engine = pyttsx3.init()
        engine.setProperty("rate",   165)
        engine.setProperty("volume", 0.9)
        print("  ✓  pyttsx3 engine initialised")
        print("     Speaking test phrases — check your speakers...")

        phrases = [
            "Oh! Hello. I am R-7.",
            "Searching... where did you go?",
            "B-beep. Systems okay!",
        ]
        for phrase in phrases:
            print(f"     > {phrase}")
            engine.say(phrase)
            engine.runAndWait()

        print("  ✓  TTS test passed\n")
        return True

    except Exception as e:
        print(f"  ✗  TTS error: {e}")
        print("     Check: sudo apt install espeak")
        return False

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
