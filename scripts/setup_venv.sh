#!/usr/bin/env bash
# Quick venv setup — just the Python packages, no system deps
set -e
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt
echo "  ✓ venv ready.  Run: source venv/bin/activate"
