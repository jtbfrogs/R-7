# Recommendations — Better Tools & Upgrades

---

## Text-to-Speech (TTS)

### pyttsx3 (current default)
- **Pros:** Zero setup, works immediately, fully offline, tiny
- **Cons:** Robotic voice quality, relies on espeak on Linux
- **Rating:** ⭐⭐⭐

### Piper TTS ⭐ RECOMMENDED UPGRADE
- **Pros:** Neural voices, natural-sounding, fast, fully offline, ~100MB models
- **Cons:** Requires model download, slightly more setup
- **Install:** `pip install piper-tts`
- **Models:** https://github.com/rhasspy/piper/releases
  - `en_US-lessac-medium` — clear, natural voice (~60MB)
  - `en_US-ryan-high` — higher quality (~120MB)
- **Config:**
  ```yaml
  audio:
    tts_engine: "piper"
    piper_model_path: "models/en_US-lessac-medium.onnx"
  ```
- **Rating:** ⭐⭐⭐⭐⭐

---

## Speech-to-Text (STT)

### Vosk (current default)
- **Pros:** Offline, small (~40MB model), fast on CPU, good accuracy for short phrases
- **Cons:** Not as accurate as Whisper
- **Model:** `vosk-model-small-en-us` from https://alphacephei.com/vosk/models
- **Rating:** ⭐⭐⭐⭐

### Whisper (OpenAI, local) ⭐ RECOMMENDED UPGRADE
- **Pros:** Excellent accuracy, runs offline, handles accents well
- **Cons:** `tiny` model needs ~1GB RAM, real-time needs a GPU or fast CPU
- **Install:** `pip install openai-whisper`
- **Best for:** If you have a GPU or can tolerate ~2s latency per utterance
- **Rating:** ⭐⭐⭐⭐⭐ (with GPU)

---

## AI / LLM (Local Models via Ollama)

| Model         | Size   | Speed (CPU) | Quality  | Notes                         |
|---------------|--------|-------------|----------|-------------------------------|
| llama3.2:1b   | 1.3GB  | Fast        | Good     | Current default               |
| phi3:mini     | 2.3GB  | Medium      | Great    | Best at following instructions|
| gemma2:2b     | 1.6GB  | Medium      | Good     | Natural friendly tone         |
| qwen2.5:1.5b  | 1.0GB  | Fast        | Good     | Very capable for its size     |
| tinyllama     | 670MB  | Very fast   | Basic    | Fallback for weak hardware    |

**Pull a model:** `ollama pull phi3:mini`

---

## Hardware Upgrades

### Compute

| Option             | Cost   | Notes                                              |
|--------------------|--------|----------------------------------------------------|
| Current laptop/PC  | —      | Works fine, runs everything                        |
| Raspberry Pi 5     | ~$80   | Portable, low power, fits on the droid             |
| NVIDIA Jetson Orin Nano | $249 | Best option if going portable — GPU for AI      |
| Orange Pi 5        | ~$90   | Better GPU than Pi 5, good for local inference     |

### Microphone

| Option             | Notes                                              |
|--------------------|----------------------------------------------------|
| Any USB mic        | Works out of the box                               |
| ReSpeaker 4-Mic    | Circular array, far-field pickup, better wake word |
| Matrix Voice       | 8-mic array, best wake-word accuracy               |

### Serial Adapter (Roomba)

| Option      | Chip    | Notes                                      |
|-------------|---------|--------------------------------------------|
| FTDI FT232R | FT232   | Most reliable, proper RTS pin support ✓    |
| CP2102      | CP2102  | Cheap, works well, good Linux driver       |

> **Avoid** CH340-based adapters for the Roomba — RTS support is unreliable.

---

## Performance Tips

1. **Use a faster AI model** — `qwen2.5:1.5b` is surprisingly good and very fast
2. **Move Ollama to GPU** — even a GTX 1060 cuts response time from ~8s to ~1s
3. **Use systemd** to run Ollama as a service so it's always warm on boot
4. **Piper TTS** responds faster than pyttsx3 and sounds dramatically better
5. **Larger Vosk model** — `vosk-model-en-us-0.22` is more accurate, ~1.8GB

---

## ROS2 Migration Path

When the project outgrows this stack:

1. Install ROS2 Humble (Ubuntu 22.04 / Pop!_OS 22.04)
2. Use `create_robot` package for Roomba control
3. Replace `HuskyLensManager` with a ROS2 sensor node
4. Replace `BehaviorManager` with Nav2 behavior trees
5. Add SLAM with `slam_toolbox`

The current architecture was deliberately designed with ROS2 in mind —
each Manager class maps naturally to a ROS2 node.
