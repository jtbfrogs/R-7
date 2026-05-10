"""
diagnostics/compare_models.py
──────────────────────────────
Test multiple Ollama models side by side with droid-specific prompts.
Run this to decide which model works best on your hardware.

Usage
─────
    python diagnostics/compare_models.py
    python diagnostics/compare_models.py --models llama3.2:1b phi3:mini gemma2:2b
    python diagnostics/compare_models.py --pull    # auto-pull recommended models first
"""

import sys
import os
import time
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ─── Colour helpers ──────────────────────────────────────────────────────────
def _c(t, c):
    codes = {"green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m",
             "cyan": "\033[36m", "bold": "\033[1m", "dim": "\033[2m", "reset": "\033[0m"}
    return f"{codes.get(c,'')}{t}{codes['reset']}"

# ─── Droid-specific test prompts ─────────────────────────────────────────────
# These mirror what the behavior system actually sends during operation.
TEST_PROMPTS = [
    {
        "label":   "Person found",
        "prompt":  "You just spotted a person in front of you. Say a short friendly greeting.",
        "context": "Person visible ahead.",
        "want":    "Short greeting, ≤8 words, no roleplay",
    },
    {
        "label":   "Person lost",
        "prompt":  "You lost sight of the person. Say you are going to look for them.",
        "context": "No person visible.",
        "want":    "Short reaction, ≤8 words, no roleplay",
    },
    {
        "label":   "Obstacle",
        "prompt":  "You just bumped into something. React briefly.",
        "context": "Obstacle nearby.",
        "want":    "Short surprised reaction",
    },
    {
        "label":   "Roaming",
        "prompt":  "You are exploring the room on your own. Say something curious.",
        "context": "No person visible. Battery 78%.",
        "want":    "Curious short phrase",
    },
]

SYSTEM_PROMPT = (
    "You are R-7, a tiny robot. "
    "RULES: Reply with ONE short sentence, max 8 words. "
    "NO parentheses. NO stage directions. NO 'User:' or 'Robot:' labels. "
    "NO roleplay. NO storytelling. Just speak as yourself. "
    "Be friendly and slightly awkward."
)

# Models to test if none specified on CLI
DEFAULT_MODELS = [
    "tinyllama",       # current baseline
    "llama3.2:1b",    # recommended upgrade
    "qwen2.5:1.5b",   # very small, good quality
    "phi3:mini",       # best instruction following
]


def check_ollama() -> bool:
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        r.raise_for_status()
        return True
    except Exception as e:
        print(_c(f"  Ollama not running: {e}", "red"))
        print(_c("  Start it with: ollama serve", "yellow"))
        return False


def get_loaded_models() -> list[str]:
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def pull_model(name: str) -> bool:
    import subprocess
    print(_c(f"  Pulling {name}...", "cyan"))
    result = subprocess.run(["ollama", "pull", name], capture_output=False)
    return result.returncode == 0


def query_model(model: str, prompt: str, context: str) -> tuple[str, float]:
    """Send a prompt to a model. Returns (response_text, elapsed_seconds)."""
    try:
        import httpx
        import re

        full_prompt = f"[Context: {context}]\n{prompt}" if context else prompt
        payload = {
            "model":  model,
            "prompt": full_prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 60},
        }
        start = time.time()
        r = httpx.post("http://localhost:11434/api/generate", json=payload, timeout=30.0)
        elapsed = time.time() - start
        r.raise_for_status()
        raw = r.json().get("response", "").strip()

        # Apply the same sanitiser as the live system
        strips = [
            (re.compile(r"\([^)]*\)"),   ""),
            (re.compile(r"\[[^\]]*\]"),  ""),
            (re.compile(r"\b(User|Robot|AI|R-7|Human|Assistant)\s*:\s*", re.I), ""),
            (re.compile(r"[*_`#]"),      ""),
            (re.compile(r"\s{2,}"),      " "),
        ]
        text = raw
        for pattern, replacement in strips:
            text = pattern.sub(replacement, text)
        text = text.strip()
        m = re.search(r"[.!?]", text)
        clean = text[:m.end()].strip() if (m and m.start() > 0) else text.split("\n")[0].strip()

        return clean, elapsed

    except Exception as e:
        return f"[ERROR: {e}]", 0.0


def score_response(text: str) -> tuple[int, list[str]]:
    """
    Heuristic scoring of a response.
    Returns (score 0-5, list of issues).
    """
    import re
    issues = []
    score  = 5

    if not text or text.startswith("[ERROR"):
        return 0, ["no response / error"]

    word_count = len(text.split())
    if word_count > 12:
        score -= 1
        issues.append(f"too long ({word_count} words)")

    roleplay_markers = ["(", "User:", "Robot:", "sighs", "walks", "opens", "moves toward"]
    for m in roleplay_markers:
        if m in text:
            score -= 2
            issues.append(f"roleplay marker: {m!r}")
            break

    if re.search(r"\b(the robot|the droid|it says|narrator)\b", text, re.I):
        score -= 1
        issues.append("third-person reference")

    if word_count < 2:
        score -= 1
        issues.append("too short / empty")

    return max(0, score), issues


def run_comparison(models: list[str], auto_pull: bool = False) -> None:
    print()
    print(_c("  R-7 Droid — Model Comparison", "bold"))
    print(_c("  ─────────────────────────────────────────────────", "cyan"))
    print()

    if not check_ollama():
        sys.exit(1)

    loaded = get_loaded_models()
    print(f"  Loaded models: {loaded or '(none)'}")
    print()

    # Pull missing models if requested
    if auto_pull:
        for m in models:
            base = m.split(":")[0]
            if not any(l.startswith(base) for l in loaded):
                print(_c(f"  {m} not found — pulling...", "yellow"))
                pull_model(m)
        loaded = get_loaded_models()

    # Filter to only available models
    available = []
    skipped   = []
    for m in models:
        base = m.split(":")[0]
        if any(l.startswith(base) for l in loaded):
            available.append(m)
        else:
            skipped.append(m)

    if skipped:
        print(_c(f"  Skipping (not pulled): {skipped}", "yellow"))
        print(_c(f"  Re-run with --pull to download them automatically", "dim"))
        print()

    if not available:
        print(_c("  No available models to test.", "red"))
        print("  Pull models with:  ollama pull llama3.2:1b")
        sys.exit(1)

    # ── Run tests ──────────────────────────────────────────────────────────
    results: dict[str, dict] = {m: {"total_score": 0, "total_time": 0.0, "responses": []} for m in available}

    for prompt_info in TEST_PROMPTS:
        print(_c(f"  ── {prompt_info['label']} ──", "bold"))
        print(_c(f"  Prompt: \"{prompt_info['prompt'][:60]}\"", "dim"))
        print()

        for model in available:
            response, elapsed = query_model(model, prompt_info["prompt"], prompt_info["context"])
            score, issues     = score_response(response)

            results[model]["total_score"] += score
            results[model]["total_time"]  += elapsed
            results[model]["responses"].append(response)

            score_colour = "green" if score >= 4 else ("yellow" if score >= 2 else "red")
            issue_str    = f"  ⚠ {', '.join(issues)}" if issues else ""
            time_str     = f"{elapsed:.1f}s"

            print(f"    {_c(f'{model:<18}', 'cyan')}  "
                  f"{_c(f'[{score}/5]', score_colour)}  "
                  f"{_c(time_str, 'dim')}  "
                  f"\"{response[:60]}\"")
            if issues:
                print(_c(f"              {issue_str}", "yellow"))
        print()

    # ── Summary ────────────────────────────────────────────────────────────
    print(_c("  ── Summary ──", "bold"))
    print()

    max_possible = len(TEST_PROMPTS) * 5
    ranked = sorted(
        available,
        key=lambda m: (results[m]["total_score"], -results[m]["total_time"]),
        reverse=True,
    )

    for i, model in enumerate(ranked):
        r        = results[model]
        score    = r["total_score"]
        avg_time = r["total_time"] / len(TEST_PROMPTS)
        pct      = int(score / max_possible * 100)
        bar      = "█" * (pct // 10) + "░" * (10 - pct // 10)
        medal    = ["🥇", "🥈", "🥉", "  ", "  "][min(i, 4)]
        colour   = "green" if pct >= 70 else ("yellow" if pct >= 40 else "red")

        print(f"  {medal}  {_c(f'{model:<18}', 'bold')}  "
              f"{_c(bar, colour)}  {pct}%  "
              f"avg {avg_time:.1f}s/response")

    best = ranked[0]
    print()
    print(_c(f"  Recommended: {best}", "green"))
    print()
    print("  To switch models, edit config/local_config.yaml:")
    print(_c(f"    ai:", "cyan"))
    print(_c(f"      model: \"{best}\"", "cyan"))
    print()
    print("  Or set it permanently in config/default_config.yaml")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare Ollama models for R-7")
    parser.add_argument(
        "--models", nargs="+", default=DEFAULT_MODELS,
        help="Models to compare (default: tinyllama llama3.2:1b qwen2.5:1.5b phi3:mini)"
    )
    parser.add_argument(
        "--pull", action="store_true",
        help="Automatically pull missing models before testing"
    )
    args = parser.parse_args()
    run_comparison(args.models, args.pull)
