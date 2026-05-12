#!/usr/bin/env bash
# scripts/start_droid.sh
# ─────────────────────────────────────────────────────────────────────────────
# Convenience launcher — activates the venv and starts R-7.
#
# Default behaviour (no args):
#   --voice        : Vosk STT always listening + pyttsx3 TTS
#   --continuous   : no Enter key needed, truly always-on
#
# You can override everything by passing flags directly:
#   bash scripts/start_droid.sh --no-vision          # skip HuskyLens
#   bash scripts/start_droid.sh --debug              # verbose logs
#   bash scripts/start_droid.sh --no-roomba          # voice only, no hardware
#   bash scripts/start_droid.sh --voice --no-roomba  # same thing, explicit
#
# For the Vosk model (one-time download, ~40 MB):
#   bash scripts/download_vosk_model.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# ── Activate venv ─────────────────────────────────────────────────────────────
if [ ! -f "venv/bin/activate" ]; then
    echo "ERROR: venv not found. Run:  bash scripts/install_dependencies.sh"
    exit 1
fi
source venv/bin/activate

# ── Check Vosk model ─────────────────────────────────────────────────────────
MODEL_PATH="models/vosk-model-small-en-us"
if [ ! -d "$MODEL_PATH" ]; then
    echo "Vosk model not found — downloading now (~40 MB)..."
    bash scripts/download_vosk_model.sh
fi

# ── Launch ────────────────────────────────────────────────────────────────────
# Default flags: voice on, always-listening, full hardware mode.
# Any args passed to this script are forwarded to main.py, overriding defaults.
if [ $# -eq 0 ]; then
    echo "Starting R-7 (voice + continuous listening + Roomba hardware)..."
    exec python main.py --voice --continuous
else
    echo "Starting R-7 with args: $*"
    exec python main.py "$@"
fi
