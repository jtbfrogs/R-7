# R-7 Droid

> *A Star Wars-inspired AI droid companion built on a Roomba 650.*

```
  ██████╗       ███████╗
  ██╔══██╗      ╚════██║
  ██████╔╝          ██╔╝
  ██╔══██╗         ██╔╝
  ██║  ██║         ██║
  ╚═╝  ╚═╝         ╚═╝
```

R-7 is a modular AI robotics platform built on a Roomba 650.
It roams autonomously, follows people, talks using a local AI,
and behaves like a tiny, slightly awkward droid companion.

Personality inspired by **BMO** (Adventure Time) and **D-O** (Star Wars IX).

---

## Features

- 🤖 **Autonomous roaming** with obstacle avoidance
- 👤 **Person following** using computer vision
- 🔍 **Search mode** when person is lost
- 🗣️ **Local AI speech** via Ollama (fully offline)
- 🎤 **Voice command** support (offline, wake word)
- 🧠 **Personality system** — short, quirky, droid-like responses
- 🔧 **Modular architecture** — every subsystem is isolated
- 📊 **Full diagnostics** — health checks for every component
- ⚙️ **YAML config** — change everything without touching code
- 📝 **Rotating logs** — detailed logs for every subsystem

---

## Hardware Requirements

| Component        | Notes                                          |
|------------------|------------------------------------------------|
| Roomba 650       | The base robot                                 |
| PC / Laptop      | Runs the software (Linux Pop!_OS recommended)  |
| USB-UART adapter | CP2102 or FTDI FT232R (needs RTS pin!)         |
| Mini-DIN 7 cable | Or build your own from the Roomba connector    |
| USB Webcam       | Any USB webcam; Logitech C920 recommended      |
| USB Microphone   | Optional (for voice commands)                  |
| PC Speakers      | Optional (TTS output)                          |

### Wiring (UART to Roomba)

```
USB-UART Adapter    →    Roomba 650 (Mini-DIN 7-pin)
─────────────────────────────────────────────────────
TXD                 →    Pin 3 (RXD)
RXD                 →    Pin 4 (TXD)
GND                 →    Pin 6 (GND)
RTS                 →    Pin 7 (RTS — wakeup)
```

> ⚠️ **Do NOT connect** to Roomba pins 1 or 2 (raw battery voltage, ~14.4V)

Full wiring guide: [`docs/UART_GUIDE.md`](docs/UART_GUIDE.md)

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourname/r-7.git
cd r-7
```

### 2. Install Everything (recommended)

```bash
bash scripts/install_dependencies.sh         # system packages + pip + Ollama
bash scripts/install_dependencies.sh --gpu   # same but with CUDA PyTorch
```

### 3. Manual Install (alternative)

```bash
# System packages
sudo apt install python3-pip python3-venv espeak libportaudio2

# Python virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Ollama (local AI)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull tinyllama

# Serial port permissions
sudo usermod -aG dialout $USER   # log out + back in after this
```

### 4. Verify Installation

```bash
source venv/bin/activate
python diagnostics/check_all.py
```

---

## Quick Start

### Step 1: Test Serial Communication

Start here before anything else.

```bash
python roomba/roomba_test.py
```

```
[OFFLINE] > connect
  ✓  Connected and in SAFE mode

[SAFE] > beep
  ✓  Beep!

[SAFE] > forward 2
  ✓  Forward 2s

[SAFE] > status
```

### Step 2: Test Vision

```bash
python diagnostics/check_camera.py
```

### Step 3: Test AI

```bash
ollama serve &
python diagnostics/check_ollama.py
```

### Step 4: Full System Console

```bash
python commands/command_console.py
```

### Step 5: Launch the Droid

```bash
python main.py
```

Or with flags:
```bash
python main.py --no-ai          # no Ollama needed
python main.py --no-vision      # no camera needed
python main.py --debug          # verbose logging
python main.py --port /dev/ttyUSB0  # explicit port
```

---

## Repository Structure

```
r-7/
│
├── main.py                    ← Main entry point
├── requirements.txt           ← Python dependencies
├── README.md                  ← This file
├── .gitignore
│
├── config/
│   ├── default_config.yaml    ← All settings (edit this!)
│   ├── local_config.yaml      ← Personal overrides (.gitignored)
│   └── config_loader.py       ← YAML loader with deep-merge
│
├── roomba/                    ← Roomba OI serial system
│   ├── controller.py          ← High-level control (startup, drive, sensors)
│   ├── serial_manager.py      ← Low-level UART (open, send, receive, wakeup)
│   ├── opcodes.py             ← OI byte-sequence builders
│   └── roomba_test.py         ← Interactive serial test console
│
├── vision/                    ← Computer vision
│   ├── camera_manager.py      ← Background webcam capture thread
│   ├── person_detector.py     ← HOG + face cascade (+ optional PyTorch)
│   └── vision_manager.py      ← Coordinator — exposes VisionState
│
├── ai/                        ← AI / personality
│   ├── personality.py         ← Speech quirks, phrases, cooldowns
│   ├── ollama_client.py       ← Ollama HTTP API wrapper
│   └── context_builder.py     ← Builds context strings for the AI
│
├── audio/                     ← Text-to-speech + speech-to-text
│   ├── tts_manager.py         ← Non-blocking TTS queue + interruption
│   └── stt_manager.py         ← Microphone input + wake word
│
├── behaviors/                 ← Autonomous behaviour state machine
│   └── behavior_manager.py    ← FREE_ROAM / FOLLOW / SEARCH / OBSTACLE
│
├── commands/                  ← Manual control
│   └── command_console.py     ← Full system interactive terminal
│
├── utilities/                 ← Shared helpers
│   ├── constants.py           ← All magic numbers in one place
│   ├── logger.py              ← Coloured logging factory
│   └── helpers.py             ← Byte packing, port detection, etc.
│
├── diagnostics/               ← Standalone health check scripts
│   ├── check_all.py           ← Run all checks
│   ├── check_roomba_serial.py ← Deep serial diagnostic
│   ├── check_camera.py        ← Camera test with live display
│   ├── check_ollama.py        ← AI availability + inference test
│   ├── check_tts.py           ← TTS speech test
│   └── check_microphone.py    ← Microphone level test
│
├── scripts/                   ← Shell utilities
│   ├── install_dependencies.sh ← Full system installer
│   ├── setup_venv.sh           ← Python-only setup
│   └── start_droid.sh          ← Launch shortcut
│
├── docs/                      ← Documentation
│   ├── UART_GUIDE.md          ← Wiring + OI protocol deep-dive
│   ├── RECOMMENDATIONS.md     ← Better tools + hardware upgrades
│   ├── ROADMAP.md             ← Development plan
│   └── DEBUGGING.md           ← Troubleshooting guide
│
├── future_features/
│   └── FUTURE_IDEAS.md        ← Feature wishlist
│
├── logs/                      ← Rotating log files (auto-created)
└── tests/                     ← Unit tests (placeholder)
```

---

## Configuration

All settings live in `config/default_config.yaml`.

To override without touching the defaults, create `config/local_config.yaml`:

```yaml
# config/local_config.yaml  (this file is .gitignored)

roomba:
  port: "/dev/ttyUSB0"   # your actual serial port

ai:
  model: "phi3:mini"     # better model if you have RAM

audio:
  tts_engine: "piper"    # better TTS (see RECOMMENDATIONS.md)
```

Only put the settings you want to change — everything else falls back to defaults.

---

## Speech Style

R-7 speaks like this:

```
"Oh! Hi!"
"B-b-beep. I found you!"
"Searching… where did you go?"
"Uh… obstacle."
"Okay okay okay!"
"H-hi there!"
```

Adjustable in config under `personality.phrases` and `personality.stutter_chance`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "No serial ports found" | Check USB adapter, run `ls /dev/ttyUSB*` |
| "Permission denied" on port | `sudo usermod -aG dialout $USER` then log out |
| Roomba doesn't respond | Run `python diagnostics/check_roomba_serial.py` |
| RTS wakeup fails | Try a different adapter (CP2102/FTDI recommended) |
| Camera not detected | `python diagnostics/check_camera.py --index 1` |
| Ollama slow/unavailable | `ollama serve`, try tinyllama model |
| No sound | `sudo apt install espeak`, run `python diagnostics/check_tts.py` |

Full guide: [`docs/DEBUGGING.md`](docs/DEBUGGING.md)

---

## Future Plans

See [`future_features/FUTURE_IDEAS.md`](future_features/FUTURE_IDEAS.md) and
[`docs/ROADMAP.md`](docs/ROADMAP.md).

Highlights:
- YOLOv8n person detection
- Piper neural TTS
- ESP32 servo head movement
- LED emotion eyes
- SLAM room mapping
- Mobile app control
- Jetson Orin Nano migration

---

## Architecture

The system is designed as a collection of independent managers that
communicate via shared state objects — not direct calls.

```
                    ┌──────────────────┐
                    │    main.py       │
                    │  (orchestrator)  │
                    └──────┬───────────┘
              ┌────────────┼─────────────────┐
              ▼            ▼                 ▼
    ┌──────────────┐  ┌──────────┐   ┌────────────┐
    │  Roomba      │  │  Vision  │   │   Audio    │
    │  Controller  │  │  Manager │   │  TTS + STT │
    └──────┬───────┘  └────┬─────┘   └─────┬──────┘
           │               │               │
           └───────────────▼───────────────┘
                    ┌──────────────────┐
                    │  Behavior Manager│
                    │  (state machine) │
                    └──────────────────┘
                           │
                    ┌──────▼───────────┐
                    │   Personality    │
                    │   AI Client      │
                    └──────────────────┘
```

---

## License

MIT License — see LICENSE file.

---

*"B-beep. I am ready."* — R-7
