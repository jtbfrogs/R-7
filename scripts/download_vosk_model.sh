#!/usr/bin/env bash
# scripts/download_vosk_model.sh
# ──────────────────────────────
# Downloads the small English Vosk model used for offline speech recognition.
# Run once before using test_voice_chat.py or enabling voice input.
#
# Usage:
#   bash scripts/download_vosk_model.sh              # small model (~40 MB)
#   bash scripts/download_vosk_model.sh --large      # large model (~1.8 GB, better accuracy)

set -e

MODELS_DIR="$(dirname "$0")/../models"
SMALL_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
LARGE_URL="https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip"
SMALL_DIR="vosk-model-small-en-us"
LARGE_DIR="vosk-model-en-us-0.22"

mkdir -p "$MODELS_DIR"
cd "$MODELS_DIR"

if [[ "$1" == "--large" ]]; then
    URL="$LARGE_URL"
    ZIP="vosk-model-en-us-0.22.zip"
    DEST="$LARGE_DIR"
    echo "Downloading large Vosk model (~1.8 GB) — better accuracy..."
else
    URL="$SMALL_URL"
    ZIP="vosk-model-small-en-us-0.15.zip"
    DEST="$SMALL_DIR"
    echo "Downloading small Vosk model (~40 MB)..."
fi

if [ -d "$DEST" ]; then
    echo "Model already exists at models/$DEST — skipping download."
    exit 0
fi

wget -q --show-progress -O "$ZIP" "$URL"
echo "Extracting..."
unzip -q "$ZIP"
# Normalise directory name (strip version suffix for small model)
extracted=$(unzip -Z1 "$ZIP" | head -1 | cut -d/ -f1)
if [ "$extracted" != "$DEST" ]; then
    mv "$extracted" "$DEST"
fi
rm "$ZIP"

echo ""
echo "✓ Vosk model ready at: models/$DEST"
echo "  Use with: python scripts/test_voice_chat.py --model-path models/$DEST"
