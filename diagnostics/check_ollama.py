"""
diagnostics/check_ollama.py
────────────────────────────
Test Ollama connectivity and send a sample droid-style prompt.

Usage
─────
    python diagnostics/check_ollama.py
    python diagnostics/check_ollama.py --model phi3:mini
"""

import sys, os, argparse
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def run(model: str = "tinyllama") -> bool:
    print(f"\n  Testing Ollama (model: {model})...")

    try:
        import httpx
    except ImportError:
        print("  ✗  httpx not installed.  Run: pip install httpx")
        return False

    # Check server
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        print(f"  ✓  Ollama server running")
        print(f"     Loaded models: {models or '(none)'}")
    except Exception as e:
        print(f"  ✗  Ollama not running: {e}")
        print("     Start it with:  ollama serve")
        print("     Install from:   https://ollama.com")
        return False

    # Check model
    model_base = model.split(":")[0]
    found = any(m.startswith(model_base) for m in models)
    if not found:
        print(f"  ✗  Model '{model}' not loaded")
        print(f"     Pull it with:  ollama pull {model}")
        return False
    print(f"  ✓  Model '{model}' available")

    # Send test prompt
    print(f"  Testing inference (this may take a moment)...")
    payload = {
        "model":  model,
        "prompt": "You are a small friendly robot. Say hi in one sentence.",
        "stream": False,
        "options": {"num_predict": 30, "temperature": 0.7},
    }
    try:
        r = httpx.post("http://localhost:11434/api/generate", json=payload, timeout=15.0)
        r.raise_for_status()
        text = r.json().get("response", "").strip()
        print(f"  ✓  AI response: \"{text}\"")
    except Exception as e:
        print(f"  ✗  Inference failed: {e}")
        return False

    print("  ✓  Ollama test passed\n")
    return True

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="tinyllama")
    a = p.parse_args()
    sys.exit(0 if run(a.model) else 1)
