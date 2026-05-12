# R-7 Project — AI Assistant Memory
> Last updated: 2026-05-11
> Read this at the start of every session to get up to speed fast.

---

## Project Overview

**R-7** is a Star Wars-inspired AI droid companion built on a **Roomba 650**.
Personality modelled on **BMO** (Adventure Time) and **D-O** (Star Wars IX) —
short, quirky, slightly awkward responses. Fully offline AI via Ollama.

**OS: Pop!_OS (Linux)** — not macOS, not Windows. Important for audio/serial paths.

---

## Hardware

| Component           | Detail                                              |
|---------------------|-----------------------------------------------------|
| Base robot          | Roomba 650                                          |
| PC                  | Pop!_OS laptop — runs all software                  |
| USB-UART #1         | CP2102 or FTDI FT232R **with RTS pin** → Roomba     |
| USB-UART #2         | Any CP2102/CH340 → HuskyLens 2                      |
| Vision sensor       | **HuskyLens 2** — only vision sensor, no camera     |
| Microphone          | USB mic — optional, can be unplugged                |
| Speakers            | PC speakers — optional, sometimes not connected     |

### Serial port mapping (Linux)
- Roomba → `/dev/ttyUSB0` (auto-detect prefers first port)
- HuskyLens → `/dev/ttyUSB1` (auto-detect picks second port)

### Wiring — UART #1 → Roomba 650 (Mini-DIN 7-pin)
```
TXD → Pin 3 (RXD)
RXD → Pin 4 (TXD)
GND → Pin 6 (GND)
RTS → Pin 7 (wakeup)
```
**Never connect to Roomba pins 1 or 2 — raw battery ~14.4V.**

### Wiring — UART #2 → HuskyLens 2
```
TXD → RXD  (TX/RX must be CROSSED)
RXD → TXD
GND → GND
3V3 → 3V3 (or 5V — match adapter)
```

---

## Project Structure

```
r-7/
├── main.py                    # Entry point — all CLI flags live here
├── config/
│   ├── default_config.yaml    # Version-controlled defaults
│   └── local_config.yaml      # Personal overrides (.gitignored, may not exist)
├── ai/
│   ├── ollama_client.py       # Talks to local Ollama instance
│   ├── personality.py         # Phrase banks, stutter effect, cooldowns
│   ├── voice_chat.py          # VoiceChatManager — ties STT+TTS+AI together
│   └── context_builder.py     # Builds compact context strings for AI prompts
├── audio/
│   ├── stt_manager.py         # Vosk STT — wake word, RMS gate, background loop
│   └── tts_manager.py         # pyttsx3 TTS — queued + sync speak, interrupt
├── huskylens/
│   ├── huskylens_manager.py   # HuskyLens polling, state, target callbacks
│   └── protocol.py            # UART protocol implementation
├── roomba/
│   ├── controller.py          # Roomba OI — movement, sensors, modes
│   ├── serial_manager.py      # Serial port open/close/wakeup
│   ├── opcodes.py             # OI byte-level command builders
│   └── roomba_test.py         # Interactive hardware tester
├── behaviors/
│   └── behavior_manager.py    # State machine: ROAM/FOLLOW/SEARCH/OBSTACLE
├── commands/
│   └── command_console.py     # Full interactive terminal console
├── utilities/
│   ├── constants.py           # All magic numbers/strings — edit here not in code
│   ├── helpers.py             # clamp, jitter, truncate_words, pack_signed_16
│   └── logger.py              # Rotating file + console logger
├── diagnostics/
│   ├── check_all.py           # Full system health check — run this first
│   ├── check_huskylens.py     # HuskyLens sensor test
│   ├── check_microphone.py    # Microphone / audio input test
│   ├── check_ollama.py        # Ollama + model test
│   ├── check_roomba_serial.py # Roomba serial test
│   ├── check_tts.py           # TTS output test
│   └── compare_models.py      # Side-by-side Ollama model comparison
├── scripts/
│   ├── download_vosk_model.sh # One-time Vosk model download (~40MB)
│   ├── install_dependencies.sh# Full system + Python dep installer
│   ├── setup_venv.sh          # venv creation only
│   ├── start_droid.sh         # Convenience launcher (activates venv + runs main.py)
│   └── test_chat.py           # Standalone chatbot (text or --voice, no hardware)
├── tests/
│   ├── test_roomba.py         # Unit tests — Roomba opcodes + helpers (no hardware)
│   └── test_personality.py    # Unit tests — personality, stutter, cooldown
├── docs/
│   ├── DEBUGGING.md           # Troubleshooting guide per subsystem
│   ├── RECOMMENDATIONS.md     # Better TTS/STT/AI options + hardware upgrades
│   ├── ROADMAP.md             # Phase-by-phase progress tracker
│   └── UART_GUIDE.md          # Full wiring guide
├── models/
│   └── vosk-model-small-en-us/  # Vosk STT model (gitignored, ~40MB)
└── logs/
    └── droid.log              # Rotating log (5MB max, 3 backups)
```

---

## Config System

- **Two-file merge**: `default_config.yaml` (committed) + `local_config.yaml` (gitignored)
- Later values win. Only put overrides in `local_config.yaml`.
- Loaded once, cached as singleton via `get_config()`.
- Sections: `roomba`, `drive`, `huskylens`, `behavior`, `ai`, `personality`, `audio`, `logging`

**Key audio defaults:**
```yaml
audio:
  tts_engine: "pyttsx3"
  stt_engine: "vosk"
  vosk_model_path: "models/vosk-model-small-en-us"
  wake_word: "hey r-seven"
  voice_input_enabled: true
  tts_enabled: true
```

---

## Voice / Audio System

### STT (Speech-to-Text)
- **Engine**: Vosk (fully offline), model at `models/vosk-model-small-en-us/`
- **Wake word**: `"hey r-seven"` — set in both `default_config.yaml` AND explicitly
  in `VoiceChatManager.init()` to avoid the empty-string bypass bug (see bugs below)
- **RMS energy gate**: chunks below `STTManager.SILENCE_THRESHOLD = 200` are dropped
  before Vosk sees them — prevents hallucinations from silence or monitor sources
- **Flow**: `_listen_vosk()` → RMS check → `AcceptWaveform()` → `_process_text()`
  → wake word check → `_callback(command)`
- **Device logging**: STT logs the actual input device name on startup

### TTS (Text-to-Speech)
- **Engine**: pyttsx3
- `speak()` — async queued
- `speak_sync()` — blocking
- `interrupt()` — stops mid-sentence

### VoiceChatManager (`ai/voice_chat.py`)
- Ties STT + TTS + OllamaClient together
- `use_wake_word=True` → explicitly sets `cfg["audio"]["wake_word"] = WAKE_WORD`
- `use_wake_word=False` → clears wake word to `""`
- Both `VoiceChatManager` calls in `main.py` use `use_wake_word=True`

### CLI flags
```
python main.py --voice --no-roomba            # voice chat, no hardware
python main.py --voice --no-roomba --continuous  # always-listening
python main.py --voice                        # voice + Roomba + HuskyLens
python scripts/test_chat.py                   # text chatbot, no hardware
python scripts/test_chat.py --voice           # voice chatbot, no hardware
```

---

## AI

- **Ollama** running locally, default model: `llama3.2:1b`
- Recommended: `phi3:mini` (best instruction following) or `qwen2.5:1.5b` (fastest)
- Hard cap: **20 words** per response
- Cooldown: 3s between responses
- Falls back to personality phrases if Ollama unavailable

---

## Known Bugs & Fixed Issues

### ✅ FIXED — Wake word never actually worked (2026-05-11)
Three compounding bugs meant the wake word was silently disabled:
1. `default_config.yaml` had `wake_word: ""` — key present but empty
2. `STTManager` uses `.get("wake_word", WAKE_WORD)` — fallback only fires if key
   is MISSING, not when it's `""`, so `self._wake_word` was always `""`
3. `VoiceChatManager.init()` with `use_wake_word=True` did nothing — only the
   `False` branch had code
**Fix**: `default_config.yaml` now has `wake_word: "hey r-seven"`. `VoiceChatManager`
now explicitly sets the wake word either way regardless of config default.

### ✅ FIXED — Vosk hallucinating from silence / wrong input device (2026-05-11)
On Pop!_OS, PipeWire silently falls back to another input (built-in mic, monitor
source) when the USB mic is unplugged. `sounddevice` gets a valid stream with no
error. Vosk then produces hallucinated transcriptions from near-silence.
**Fix**: RMS energy gate added to `_listen_vosk()`. Chunks below
`SILENCE_THRESHOLD = 200` are discarded before Vosk sees them.
STT now also logs the actual input device name on startup.

### ✅ FIXED — Vosk C++ model-loading logs cluttering terminal (2026-05-11)
`SetLogLevel(-1)` called before model load silences the VoskAPI internal logs.

---

## Running the Project

```bash
cd /path/to/r-7
source venv/bin/activate

python main.py                          # full autonomous mode
python main.py --voice                  # + always-listening voice
python main.py --no-vision              # skip HuskyLens
python main.py --debug                  # verbose logging

python commands/command_console.py      # interactive terminal control
python scripts/test_chat.py             # text chatbot (no hardware)
python scripts/test_chat.py --voice     # voice chatbot (no hardware)
python diagnostics/check_all.py         # full system health check
bash scripts/start_droid.sh             # convenience launcher
```

---

## Gotchas

- **Pop!_OS audio fallback**: When USB mic is unplugged, PipeWire silently
  switches to another input device. No error thrown. RMS gate mitigates this
  but device name in logs will reveal if it's using the wrong source.
- **Wake word is "hey r-seven"** — Vosk hears it as two words, no hyphen
- **Serial port order**: Roomba must be on ttyUSB0, HuskyLens on ttyUSB1.
  If ports swap on reboot, use stable `/dev/serial/by-id/` paths in local_config.
- **Ollama must be running**: `ollama serve` — or set up as a systemd service
- **dialout group**: User must be in `dialout` group for serial access.
  Run `sudo usermod -aG dialout $USER` then **log out and back in**.
