#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  scripts/install_dependencies.sh
#  R-7 Droid — Dependency installer for Pop!_OS / Ubuntu
#
#  Usage:
#     bash scripts/install_dependencies.sh
#     bash scripts/install_dependencies.sh --gpu     (include CUDA PyTorch)
#     bash scripts/install_dependencies.sh --no-tts  (skip espeak)
# ═══════════════════════════════════════════════════════════════════════════════

set -e  # exit on any error

CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { echo -e "${CYAN}  ▸  $1${RESET}"; }
ok()    { echo -e "${GREEN}  ✓  $1${RESET}"; }
warn()  { echo -e "${YELLOW}  !  $1${RESET}"; }
fail()  { echo -e "${RED}  ✗  $1${RESET}"; }
section(){ echo -e "\n${BOLD}  ── $1 ──${RESET}"; }

GPU_MODE=false
SKIP_TTS=false

for arg in "$@"; do
    case $arg in
        --gpu)    GPU_MODE=true ;;
        --no-tts) SKIP_TTS=true ;;
    esac
done

echo ""
echo -e "${BOLD}  R-7 Droid — Dependency Installer${RESET}"
echo -e "${CYAN}  ────────────────────────────────────${RESET}"
echo ""

# ── Check Python ───────────────────────────────────────────────────────────────
section "Checking Python"
if python3 --version &>/dev/null; then
    PYVER=$(python3 --version)
    ok "Python: $PYVER"
else
    fail "Python 3 not found"
    info "Install it: sudo apt install python3 python3-pip python3-venv"
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
    "v4l-utils"
    "ffmpeg"
    "aplay"
)

if [ "$SKIP_TTS" = false ]; then
    PACKAGES+=("espeak" "espeak-data" "libespeak1" "libespeak-dev")
fi

for pkg in "${PACKAGES[@]}"; do
    if dpkg -l "$pkg" &>/dev/null; then
        ok "$pkg (already installed)"
    else
        info "Installing $pkg..."
        sudo apt-get install -y -qq "$pkg" && ok "$pkg" || warn "Failed to install $pkg"
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
ok "venv active — using: $(which python)"

# ── Upgrade pip ────────────────────────────────────────────────────────────────
info "Upgrading pip..."
pip install --upgrade pip --quiet

# ── Core Python packages ───────────────────────────────────────────────────────
section "Core Python packages"
CORE_PACKAGES=(
    "pyserial"
    "pyyaml"
    "opencv-python"
    "numpy"
    "httpx"
    "pyttsx3"
)

for pkg in "${CORE_PACKAGES[@]}"; do
    info "Installing $pkg..."
    pip install "$pkg" --quiet && ok "$pkg" || fail "$pkg failed"
done

# ── Optional: PyTorch ──────────────────────────────────────────────────────────
section "PyTorch (person detection)"
if [ "$GPU_MODE" = true ]; then
    info "Installing PyTorch with CUDA support..."
    warn "This is a large download (~2GB+)"
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118 --quiet \
        && ok "PyTorch + CUDA installed" \
        || warn "PyTorch GPU install failed — trying CPU version..."
    pip install torch torchvision --quiet && ok "PyTorch CPU fallback installed" || true
else
    info "Installing PyTorch (CPU only — use --gpu for CUDA)..."
    pip install torch torchvision --quiet && ok "PyTorch installed" || warn "PyTorch failed — vision will use HOG"
fi

# ── Optional: Audio / STT ─────────────────────────────────────────────────────
section "Audio / Speech Recognition (optional)"
info "Installing sounddevice..."
pip install sounddevice --quiet && ok "sounddevice" || warn "sounddevice failed"

info "Installing vosk (offline STT)..."
pip install vosk --quiet && ok "vosk" || warn "vosk failed — voice input disabled"

# ── Serial port permissions ────────────────────────────────────────────────────
section "Serial port permissions"
if groups $USER | grep -q dialout; then
    ok "User '$USER' is in the 'dialout' group"
else
    warn "User '$USER' is NOT in the 'dialout' group"
    info "Adding to dialout group (requires logout to take effect)..."
    sudo usermod -aG dialout $USER
    warn "You MUST log out and log back in for serial permissions to work!"
fi

# ── Ollama ─────────────────────────────────────────────────────────────────────
section "Ollama (local AI)"
if command -v ollama &>/dev/null; then
    ok "Ollama already installed: $(ollama --version 2>/dev/null || echo 'unknown version')"
else
    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    ok "Ollama installed"
fi

info "Pulling tinyllama model (~670MB — this may take a few minutes)..."
if ollama pull tinyllama; then
    ok "tinyllama model ready"
else
    warn "Failed to pull tinyllama — try manually: ollama pull tinyllama"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  ── Installation Complete ──${RESET}"
echo ""
ok "All core dependencies installed"
echo ""
echo "  Next steps:"
echo -e "${CYAN}    1. source venv/bin/activate          # activate venv${RESET}"
echo -e "${CYAN}    2. python diagnostics/check_all.py   # verify everything${RESET}"
echo -e "${CYAN}    3. python roomba/roomba_test.py       # test Roomba serial${RESET}"
echo -e "${CYAN}    4. python main.py                     # launch droid!${RESET}"
echo ""
echo -e "${YELLOW}  Remember: if you just added yourself to 'dialout', LOG OUT first!${RESET}"
echo ""
