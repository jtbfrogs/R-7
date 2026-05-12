# Development Roadmap

## Phase 0 — Foundation ✅
- [x] Repository structure
- [x] Config system (YAML, default + local override)
- [x] Logging + rotation
- [x] Roomba serial manager
- [x] Roomba controller (safe/full/passive modes, all OI opcodes)
- [x] Interactive roomba_test.py
- [x] Serial diagnostics

## Phase 1 — Basic Movement & Speech ✅
- [x] Serial communication on real hardware
- [x] All movement commands (forward, back, spin, stop)
- [x] Sensor reads (battery, bumpers, OI mode)
- [x] TTS speaking via pyttsx3
- [x] Startup greeting
- [x] command_console.py fully functional

## Phase 2 — Vision (HuskyLens 2) ✅
- [x] HuskyLens 2 UART protocol
- [x] HuskyLensManager (polling, state, callbacks)
- [x] Face recognition mode
- [x] Object tracking mode
- [x] Target detection flowing to BehaviorManager
- [x] Follow-person behaviour with steering

## Phase 3 — Autonomous Behaviour ✅
- [x] Free roam mode with obstacle avoidance (bump sensors)
- [x] Search-for-person mode (spin + timeout)
- [x] Behaviour state machine (IDLE → ROAM → FOLLOW → SEARCH)
- [x] Speech reactions to state transitions

## Phase 4 — AI & Voice ✅
- [x] Ollama integration (local LLM, fully offline)
- [x] AI responses wired into behaviour
- [x] Personality filter (word cap, stutter effect)
- [x] Vosk offline STT with wake word ("hey r-seven")
- [x] RMS energy gate (blocks silence/false triggers)
- [x] TTS interrupt-on-speech (mic always wins)
- [x] Voice chat mode (--voice --no-roomba)

## Phase 5 — Polish & Reliability
- [ ] Upgrade to Piper TTS (much better voice quality)
- [ ] Battery monitoring + low-battery auto-dock
- [ ] Crash recovery (auto-reconnect on serial loss)
- [ ] Web status dashboard (Flask, simple read-only)
- [ ] HuskyLens algorithm hot-switching via voice command

## Phase 6 — Advanced Features
- [ ] ESP32 head pan/tilt (turns toward detected person)
- [ ] LED/OLED emotion eyes
- [ ] Droid sound pack (R2-D2 style beeps mixed with TTS)
- [ ] Scheduled cleaning mode (use Roomba's built-in clean)
- [ ] Docking on low battery (OI SEEK_DOCK)

## Phase 7 — Future Horizons
- [ ] SLAM mapping (know the room layout)
- [ ] Room memory ("I was here before")
- [ ] Person memory (recognise and greet people by name)
- [ ] Mobile app companion (live status + manual control)
- [ ] Jetson Orin Nano migration (for portable + GPU inference)
- [ ] ROS2 migration
