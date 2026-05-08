# Development Roadmap

## Phase 0 — Foundation ✅ (current)
- [x] Repository structure
- [x] Config system (YAML)
- [x] Logging + rotation
- [x] Roomba serial manager
- [x] Roomba controller (safe/full/passive modes)
- [x] All OI opcodes
- [x] Interactive roomba_test.py
- [x] Serial diagnostics

## Phase 1 — Basic Movement & Speech
- [ ] Verify serial communication on real hardware
- [ ] Test all movement commands (forward, back, spin, stop)
- [ ] Verify sensor reads (battery, bumpers, OI mode)
- [ ] TTS speaking via pyttsx3
- [ ] Startup greeting works
- [ ] command_console.py fully functional

## Phase 2 — Vision Integration
- [ ] Camera feed stable
- [ ] HOG person detection working
- [ ] Face detection working
- [ ] VisionState flowing to BehaviorManager
- [ ] Follow-person behaviour (basic steering)
- [ ] Debug display window

## Phase 3 — Autonomous Behaviour
- [ ] Free roam mode with obstacle avoidance
- [ ] Search-for-person mode
- [ ] Behaviour state transitions smooth
- [ ] Droid "feels alive" during testing
- [ ] Speech reactions to state changes

## Phase 4 — AI Personality
- [ ] Ollama running with tinyllama
- [ ] AI responses integrated into behaviour
- [ ] Personality filter working
- [ ] Stutter/quirks tuned
- [ ] Voice input (Vosk + wake word)
- [ ] Interrupt-on-speech working

## Phase 5 — Polish & Reliability
- [ ] Upgrade to Piper TTS
- [ ] Upgrade to YOLOv8n detection
- [ ] Smooth person tracking with DeepSORT
- [ ] Battery monitoring + low-battery dock behaviour
- [ ] Crash recovery (auto-reconnect on serial loss)
- [ ] Web status dashboard

## Phase 6 — Advanced Features
- [ ] SLAM mapping (map the room)
- [ ] Room memory (knows its environment)
- [ ] Scheduled cleaning mode
- [ ] ESP32 head/servo control
- [ ] Droid emotion display (eyes/LED)
- [ ] Sound packs (R2-D2 style beeps)

## Phase 7 — Future Horizons
- [ ] Multi-personality support
- [ ] Object memory ("I saw the chair there before")
- [ ] Remote control via web interface
- [ ] Mobile app companion
- [ ] Jetson Orin Nano migration
- [ ] ROS2 migration path
