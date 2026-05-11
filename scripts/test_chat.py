#!/usr/bin/env python3
"""
scripts/test_chat.py
─────────────────────
Quick interactive chatbot tester — no robot hardware needed.

Usage
─────
  cd /Users/jtb/src/r-7
  source venv/bin/activate
  python scripts/test_chat.py                       # use config model
  python scripts/test_chat.py --model gemma3:270m   # pick a specific model
  python scripts/test_chat.py --raw                 # show raw model output before sanitising

Type a message and press Enter.  Type 'quit' or Ctrl-C to exit.
"""

import sys
import argparse
from pathlib import Path

# ── Make sure project root is on sys.path ─────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ai.ollama_client import OllamaClient, _sanitise, _SYSTEM_PROMPT
from utilities.constants import OLLAMA_DEFAULT_MODEL


def parse_args():
    p = argparse.ArgumentParser(description="Interactive R-7 chatbot test")
    p.add_argument("--model",  default=None, help="Override model (e.g. gemma3:270m)")
    p.add_argument("--raw",    action="store_true", help="Also print raw model output")
    p.add_argument("--context", default="", help="Optional context string to inject")
    return p.parse_args()


def main():
    args = parse_args()

    ai = OllamaClient()

    # Override model if requested
    if args.model:
        ai._model = args.model
        ai._available = None   # force re-check with new model name

    print()
    print("══════════════════════════════════════════")
    print("  R-7 Chatbot Tester")
    print("══════════════════════════════════════════")
    print(f"  Model   : {ai._model}")
    print(f"  Host    : {ai._host}")
    print(f"  Max words: {ai._max_words}")
    if args.context:
        print(f"  Context : {args.context}")
    print()
    print("  System prompt:")
    for line in _SYSTEM_PROMPT.split(". "):
        print(f"    {line.strip()}")
    print()
    print("  Type a message, then Enter.  'quit' to exit.")
    print("══════════════════════════════════════════")
    print()

    if not ai.is_available():
        print("✗ Ollama is not available or model not loaded.")
        print(f"  Run: ollama pull {ai._model}")
        print( "  Run: ollama serve")
        sys.exit(1)

    print(f"✓ Ollama ready  ({ai._model})\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        response = ai.ask(user_input, context=args.context or None)

        if response:
            print(f"R-7: {response}\n")
        else:
            print("R-7: (no response — Ollama timed out or failed)\n")


if __name__ == "__main__":
    main()
