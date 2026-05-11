#!/usr/bin/env python3
"""
scripts/test_voice_chat.py  — DEPRECATED
─────────────────────────────────────────
Voice chat has been merged into the main chatbot script.

Use this instead:
  python scripts/test_chat.py --voice
  python scripts/test_chat.py --voice --continuous
  python scripts/test_chat.py --voice --list-voices
  python scripts/test_chat.py --voice --model gemma3:270m
  python scripts/test_chat.py --voice --rate 140
  python scripts/test_chat.py --voice --vosk-model models/vosk-model-en-us-0.22

Run with --help for all options:
  python scripts/test_chat.py --help
"""

import subprocess
import sys

print(__doc__)
print("Redirecting to: python scripts/test_chat.py --voice", " ".join(sys.argv[1:]))
print()

subprocess.run(
    [sys.executable, "scripts/test_chat.py", "--voice"] + sys.argv[1:],
)
