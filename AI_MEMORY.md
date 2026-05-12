# R-7 Project — AI Assistant Memory
> Last updated: 2026-05-11
> Read this at the start of every session to get up to speed fast.

---

## Project Overview

**R-7** is a Star Wars-inspired AI droid companion built on a **Roomba 650**.
Personality modelled on **BMO** (Adventure Time) and **D-O** (Star Wars IX) —
short, quirky, slightly awkward responses. Fully offline AI via Ollama.

**OS: Pop!_OS (Linux)** — not macOS, not Windows. Important for audio/serial device paths.

---

## Hardware

| Component           | Detail                                              |
|---------------------|-----------------------------------------------------|
| Base robot          | Roomba 650                                          |
| PC                  | Pop!_OS laptop — runs all software                  |
| USB-UART #1         | CP2102 or FTDI FT232R **with RTS pin** → Roomba     |
| USB-UART #2         | Any CP2102/CH340 → HuskyLens 2                      |
| Vision sensor       | HuskyLens 2 (face/object/colour/tag recognition)    |
| Microphone          | USB mic — **optional, can be unplugged**            |
| Speakers            | PC speakers — **optional, sometimes not connected** |

### Serial port mapping (Linux)
- Roomba → `/dev/ttyUSB0` (auto-detect prefers this)
- HuskyLens → `/dev/ttyUSB1` (auto-detect picks the second one)

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
│   ├── default_config.yaml    # Version-controlled defaults (edit this)
│   └── local_config.yaml      # Personal overrides (.gitignored, may not exist)
├── ai/
│   ├── ollama_client.py       # Talks to local Ollama instance
│   ├── personality.py         # Phrase banks, stutter effect, cooldowns
│   ├── voice_chat.py          # VoiceChatManager — ties STT+TTS+AI together
│   └── context_builder.py
├── audio/
│   ├── stt_manager.py         # Speech-to-text (Vosk offline or Google)
│   └── tts_manager.py         # Text-to-speech (pyttsx3)
├── roomba/
│   └── controller.py          # Roomba OI protocol, serial comms
├── huskylens/
│   └── huskylens_manager.py   # HuskyLens polling + algorithm control
├── behaviors/
│   └── behavior_manager.py    # State machine: roam/follow/search/dock
├── vision/                    # Camera + person detection (separate from HuskyLens)
├── commands/
│   └── command_console.py     # Interactive terminal control
├── utilities/
│   ├── constants.py           # ALL magic numbers/strings centralised here
│   └── logger.py
├── diagnostics/               # Health-check scripts per subsystem
├── scripts/                   # One-off helpers (download_vosk_model.sh etc.)
├── models/                    # Vosk model lives here (gitignored, ~40MB)
│   └── vosk-model-small-en-us/
└── tests/
```

---

## Config System

- **Two-file merge**: `default_config.yaml` (committed) + `local_config.yaml` (gitignored, optional)
- Later values win. Only put overrides in local_config.
- Loaded once, cached as singleton via `get_config()`.
- Sections: `roomba`, `drive`, `huskylens`, `behavior`, `ai`, `personality`, `audio`, `logging`

**Key audio config defaults:**
```yaml
audio:
  tts_engine: "pyttsx3"
  stt_engine: "vosk"
  vosk_model_path: "models/vosk-model-small-en-us"
  wake_word: ""          # ← empty = no wake word (dangerous — see bugs below)
  voice_input_enabled: true
  tts_enabled: true
```

---

## Voice / Audio System

### STT (Speech-to-Text)
- **Engine**: Vosk (fully offline) — model at `models/vosk-model-small-en-us/`
- **Wake word**: `"hey r-seven"` (defined in `utilities/constants.py` as `WAKE_WORD`)
- **Flow**: `_listen_vosk()` → `_process_text()` → wake word check → `_callback(command)`
- Wake word check in `_process_text()`: `if self._wake_word and self._wake_word not in text`
  - ⚠️ Empty string is falsy — if wake_word is `""` **everything passes through**
- `listen_once()` — synchronous, no wake word filtering, used by interactive mode
- `set_heard_callback()` — fires for ALL speech (terminal display, pre-wake-word filter)

### TTS (Text-to-Speech)
- **Engine**: pyttsx3
- `speak()` — async (queued)
- `speak_sync()` — blocking
- `interrupt()` — stops current speech immediately

### VoiceChatManager (`ai/voice_chat.py`)
- Ties STT + TTS + OllamaClient together
- Two modes:
  - **`run_interactive()`** — foreground blocking loop, push-to-talk or continuous
  - **`start_background()`** — daemon thread alongside Roomba hardware
- `use_wake_word=True/False` parameter controls whether wake word is enforced
  - Setting `False` clears `cfg["audio"]["wake_word"]` to `""`

### CLI flags
```
python main.py --voice --no-roomba            # voice chat, no hardware
python main.py --voice --no-roomba --continuous  # always-listening
python main.py --voice                        # voice + Roomba hardware
```

---

## AI

- **Ollama** running locally, default model: `llama3.2:1b`
- Recommended upgrade path: `phi3:mini` > `llama3.2:3b` > `gemma2:2b` > `llama3.2:1b` > `tinyllama`
- Hard cap: **20 words** per response (keep it droid-like)
- Cooldown: 3s between responses
- Falls back to personality phrases if Ollama unavailable

---

## Known Bugs / Fixed Issues

### ✅ FIXED — Wake word disabled, R-7 transcribed ambient audio as commands
**Date**: 2026-05-11
**Symptom**: Every ambient sound (room noise, background conversation) was logged as a
`Voice command received` even though nothing was spoken to R-7. On startup,
R-7 immediately transcribed its own greeting as a voice command.
**Root cause**: Both `VoiceChatManager` instantiations in `main.py` had
`use_wake_word=False`, which cleared the wake word to `""`. Empty string is
falsy so the wake word guard in `_process_text()` was silently bypassed.
Additionally the microphone was **unplugged** — on Pop!_OS, PulseAudio/PipeWire
silently falls back to the next available input device (e.g. built-in mic),
so `sounddevice` never threw an error and just kept listening to ambient audio.
**Fix**: Set `use_wake_word=True` in both `VoiceChatManager(...)` calls in `main.py`
(hardware mode at ~line 152, voice-only mode at ~line 262).

---

## Behaviours (State Machine)

States: `ROAMING` → `SEARCHING` → `FOLLOWING` → `OBSTACLE_AVOID` → `DOCKING`

- Requires both Roomba **and** HuskyLens to run
- Skipped entirely with `--no-behaviour` or if HuskyLens fails to connect
- `BehaviorManager` lives in `behaviors/behavior_manager.py`

---

## Personality Phrases

Defined in `default_config.yaml` under `personality.phrases` — categories:
`startup`, `person_found`, `person_lost`, `obstacle_detected`, `roaming`,
`docking`, `confused`, `happy`, `farewell` (check file for full list).

Stutter effect: `stutter_chance: 0.15` — randomly repeats a word (e.g. "H-hi!")

---

## Running the Project

```bash
cd /Users/jtb/src/r-7
source venv/bin/activate

# Full autonomous mode
python main.py

# Voice chat only (no hardware needed)
python main.py --voice --no-roomba

# Always-listening voice chat
python main.py --voice --no-roomba --continuous

# Interactive terminal control
python commands/command_console.py

# Diagnostics
python diagnostics/check_all.py
```

---

## Things Still To Do / Watch Out For

- **Audio device fallback on Linux**: When USB mic is unplugged, PulseAudio silently
  switches to another input. No error is raised by sounddevice. Would be good to add
  a startup check that verifies the expected audio device and warns if it falls back.
- **TTS silent sometimes**: Speaker not always connected. Should detect and warn.
- **Wake word in config vs code**: `default_config.yaml` has `wake_word: ""` but
  `constants.py` has `WAKE_WORD = "hey r-seven"`. The config takes precedence.
  Consider setting `wake_word: "hey r-seven"` in default_config.yaml to be consistent.
