# Recommendations — Better Tools & Upgrades

This document recommends better alternatives to the defaults,
along with hardware upgrades and performance improvements.

---

## Text-to-Speech (TTS) Comparison

### pyttsx3 (current default)
- **Pros:** Zero setup, works immediately, offline, tiny
- **Cons:** Robotic voice quality, limited on Linux (relies on espeak)
- **When to use:** Getting started, testing movement, CI/CD
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

### Coqui TTS
- **Pros:** Many voices, good quality, supports fine-tuning
- **Cons:** Heavier to install (~1GB+), slower than Piper, project archived
- **Install:** `pip install TTS`
- **Best for:** Custom voice training (make the droid sound like R2-D2)
- **Rating:** ⭐⭐⭐⭐

### XTTS v2 (Coqui)
- **Pros:** Voice cloning, multilingual, expressive
- **Cons:** Needs GPU for real-time, large model
- **Best for:** If you want the droid to clone a specific voice
- **Rating:** ⭐⭐⭐⭐ (with GPU)

---

## Speech-to-Text (STT) Comparison

### Vosk (current default)
- **Pros:** Offline, small (~40MB model), fast on CPU, good accuracy for short phrases
- **Cons:** Not as accurate as online services
- **Model:** `vosk-model-small-en-us-0.15` (~40MB) from https://alphacephei.com/vosk/models
- **Rating:** ⭐⭐⭐⭐

### Whisper (OpenAI, local)
- **Pros:** Excellent accuracy, runs offline, multiple languages
- **Cons:** `tiny` model needs 1GB RAM, real-time needs GPU
- **Install:** `pip install openai-whisper`
- **Best for:** If you have a GPU or can tolerate ~2s latency
- **Rating:** ⭐⭐⭐⭐⭐ (with GPU)

### SpeechRecognition + Google
- **Pros:** Excellent accuracy, free tier
- **Cons:** **Requires internet**, privacy concerns
- **When to use:** Development testing only
- **Rating:** ⭐⭐⭐ (for dev)

---

## Person Detection Comparison

### OpenCV HOG (current default)
- **Pros:** No model download, works on CPU, always available
- **Cons:** Less accurate than neural models, sensitive to lighting
- **Rating:** ⭐⭐⭐

### MobileNet SSD (torch, current optional)
- **Pros:** Good accuracy, fast enough for 5–10 FPS on CPU
- **Cons:** Needs torch + torchvision (~1GB)
- **Rating:** ⭐⭐⭐⭐

### YOLOv8n (nano) ⭐ RECOMMENDED UPGRADE
- **Pros:** Excellent accuracy, runs 15+ FPS on CPU, tiny model (6MB)
- **Cons:** Needs `ultralytics` package
- **Install:** `pip install ultralytics`
- **Usage:**
  ```python
  from ultralytics import YOLO
  model = YOLO("yolov8n.pt")
  results = model(frame)
  ```
- **Rating:** ⭐⭐⭐⭐⭐

### MediaPipe
- **Pros:** Extremely fast, runs on CPU, includes pose + hands + face mesh
- **Cons:** Google-maintained (may change), less generic object detection
- **Best for:** Face detection, body pose tracking
- **Install:** `pip install mediapipe`
- **Rating:** ⭐⭐⭐⭐⭐ (for face/pose)

### DeepSORT (tracking)
- **Use alongside YOLO** for smooth person tracking across frames.
  Keeps the same person ID even if detection misses a frame.
- **Install:** `pip install deep-sort-realtime`
- **Rating:** ⭐⭐⭐⭐ (combined with YOLO)

---

## AI / LLM Comparison (Local Models)

| Model         | Size   | Speed (CPU) | Quality  | Notes                    |
|---------------|--------|-------------|----------|--------------------------|
| tinyllama     | 670MB  | Fast        | Basic    | Good starting point      |
| phi3:mini     | 2.3GB  | Medium      | Good     | Microsoft, good at instructions |
| gemma:2b      | 1.4GB  | Medium      | Good     | Google, friendly tone    |
| mistral:7b-q4 | 4.1GB  | Slow on CPU | Excellent| Best quality, needs GPU  |
| llama3.2:1b   | 1.3GB  | Fast        | Good     | Meta's small model       |

**Recommendation:** Start with `tinyllama`, upgrade to `phi3:mini` once the
serial/movement/vision stack is working reliably.

---

## Hardware Upgrades

### Compute

| Option          | Cost  | Notes                                              |
|-----------------|-------|----------------------------------------------------|
| Intel NUC       | $200+ | Good balance of size and power. Current approach.  |
| NVIDIA Jetson Nano | $100–150 | GPU for vision + AI, designed for robotics   |
| Jetson Orin Nano | $249 | Excellent — runs YOLO at 30fps, Whisper real-time |
| Raspberry Pi 5  | $80   | Cheap, limited GPU. Good for Piper + HOG.          |
| Orange Pi 5     | $90   | Better GPU than Pi 5, good Mali GPU                |

> **Recommendation:** If you want to run YOLOv8 + Piper + phi3 simultaneously,
> a **Jetson Orin Nano** is the ideal platform upgrade.

### Camera

| Option          | Notes                                         |
|-----------------|-----------------------------------------------|
| Logitech C920   | Solid 1080p, good low-light, reliable on Linux |
| Raspberry Pi Camera v3 | Wide-angle version great for room coverage |
| Intel RealSense D435i | Adds depth sensing for real obstacle detection |
| OAK-D Lite      | AI-accelerated, runs YOLOv5 on-device         |

### Microphone

| Option          | Notes                                         |
|-----------------|-----------------------------------------------|
| ReSpeaker 4-Mic | Circular array, far-field pickup, USB, $20    |
| Matrix Voice    | 8-mic array, better wake-word accuracy        |
| USB lapel mic   | Cheap starting point                          |

### Serial Adapter

| Option   | Chip   | Notes                                |
|----------|--------|--------------------------------------|
| FTDI FT232R | FT232 | Most reliable, proper RTS support  |
| CP2102    | CP2102 | Cheap, works well, good Linux driver |

> **Avoid** CH340-based adapters for the Roomba — RTS support is inconsistent.

---

## Performance Tips

1. **Reduce camera resolution** to 320×240 for faster detection on CPU
2. **Increase frame skip** to run detection every 3–4 frames instead of 2
3. **Disable motion tracking** if you don't need it (not yet implemented)
4. **Use a faster AI model** — tinyllama at q4 is very fast
5. **Move Ollama to GPU** — even a GTX 1060 makes a huge difference
6. **Use systemd** to run Ollama as a service so it's always warm
7. **Pin the process to CPU cores** with `taskset` for consistent latency

---

## ROS2 Migration Path

When the project outgrows this stack:

1. Install ROS2 Humble (Ubuntu 22.04 / Pop!_OS 22.04)
2. Use `create_robot` package for Roomba control
3. Replace `VisionManager` with ROS2 `image_pipeline`
4. Replace `BehaviorManager` with Nav2 behavior trees
5. Add SLAM with `slam_toolbox`

The current architecture was deliberately designed with ROS2 in mind —
each `Manager` class maps naturally to a ROS2 node.
