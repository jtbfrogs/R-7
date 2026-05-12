#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  scripts/install_dependencies.sh
#  R-7 Droid — Dependency installer for Pop!_OS / Ubuntu
#
#  Usage:
#     bash scripts/install_dependencies.sh
#     bash scripts/install_dependencies.sh --no-tts   (skip espeak install)
# ═══════════════════════════════════════════════════════════════════════════════

set -e

CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}  ▸  $1${RESET}"; }
ok()      { echo -e "${GREEN}  ✓  $1${RESET}"; }
warn()    { echo -e "${YELLOW}  !  $1${RESET}"; }
fail()    { echo -e "${RED}  ✗  $1${RESET}"; }
section() { echo -e "\n${BOLD}  ── $1 ──${RESET}"; }

SKIP_TTS=false
for arg in "$@"; do
    case $arg in --no-tts) SKIP_TTS=true ;; esac
done

echo ""
echo -e "${BOLD}  R-7 Droid — Dependency Installer${RESET}"
echo -e "${CYAN}  ────────────────────────────────────${RESET}"
echo ""

# ── Check Python ───────────────────────────────────────────────────────────────
section "Checking Python"
if python3 --version &>/dev/null; then
    ok "Python: $(python3 --version)"
else
    fail "Python 3 not found"
    info "Install: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# ── System packages ────────────────────────────────────────────────────────────
section "System packages (apt)"
info "Updating apt..."
sudo apt-get update -qq

PACKAGES=(
    "python3-pip"
    "python3-venv"
    "python3-dev"
    "libportaudio2"
    "portaudio19-dev"
    "libasound2-dev"
)

if [ "$SKIP_TTS" = false ]; then
    PACKAGES+=("espeak" "espeak-data" "libespeak1" "libespeak-dev")
fi

for pkg in "${PACKAGES[@]}"; do
    if dpkg -l "$pkg" &>/dev/null; then
        ok "$pkg (already installed)"
    else
        info "Installing $pkg..."
        sudo apt-get install -y -qq "$pkg" && ok "$pkg" || warn "Failed: $pkg"
    fi
done

# ── Virtual environment ────────────────────────────────────────────────────────
section "Python virtual environment"
if [ ! -d "venv" ]; then
    info "Creating virtual environment in ./venv ..."
    python3 -m venv venv
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

info "Activating virtual environment..."
source venv/bin/activate
ok "venv active — $(which python)"

info "Upgrading pip..."
pip install --upgrade pip --quiet

# ── Python packages ────────────────────────────────────────────────────────────
section "Python packages"
PACKAGES=(
    "pyserial"
    "pyyaml"
    "numpy"
    "httpx"
    "pyttsx3"
    "vosk"
    "sounddevice"
)

for pkg in "${PACKAGES[@]}"; do
    info "Installing $pkg..."
    pip install "$pkg" --quiet && ok "$pkg" || fail "$pkg failed"
done

# ── Serial port permissions ────────────────────────────────────────────────────
section "Serial port permissions"
if groups $USER | grep -q dialout; then
    ok "User '$USER' is already in the 'dialout' group"
else
    warn "User '$USER' is NOT in the 'dialout' group"
    info "Adding to dialout group..."
    sudo usermod -aG dialout $USER
    warn "LOG OUT and back in for serial permissions to take effect!"
fi

# ── Ollama ─────────────────────────────────────────────────────────────────────
section "Ollama (local AI)"
if command -v ollama &>/dev/null; then
    ok "Ollama already installed: $(ollama --version 2>/dev/null || echo 'installed')"
else
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    ok "Ollama installed"
fi

info "Pulling llama3.2:1b model (~1.3 GB)..."
if ollama pull llama3.2:1b; then
    ok "llama3.2:1b ready"
else
    warn "Model pull failed — try manually: ollama pull llama3.2:1b"
fi

# ── Vosk model ─────────────────────────────────────────────────────────────────
section "Vosk speech model"
MODEL_PATH="models/vosk-model-small-en-us"
if [ -d "$MODEL_PATH" ]; then
    ok "Vosk model already present"
else
    info "Downloading Vosk model (~40 MB)..."
    bash scripts/download_vosk_model.sh && ok "Vosk model ready" || warn "Download failed — run: bash scripts/download_vosk_model.sh"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  ── Done ──${RESET}"
echo ""
ok "All dependencies installed"
echo ""
echo "  Next steps:"
echo -e "${CYAN}    1. source venv/bin/activate${RESET}"
echo -e "${CYAN}    2. python diagnostics/check_all.py      # verify everything${RESET}"
echo -e "${CYAN}    3. python diagnostics/check_huskylens.py${RESET}"
echo -e "${CYAN}    4. python roomba/roomba_test.py          # test Roomba serial${RESET}"
echo -e "${CYAN}    5. python main.py                        # launch droid${RESET}"
echo ""
if groups $USER | grep -q dialout; then
    true
else
    echo -e "${YELLOW}  ⚠  Remember to LOG OUT first for serial port permissions!${RESET}"
    echo ""
fi
