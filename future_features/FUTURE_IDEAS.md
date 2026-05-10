# Future Feature Ideas

This file is a living document — a brain dump of everything R-7 could
eventually become.  Nothing here is committed to, just explored.

---

## Tier 1 — Near-Term (Phase 5–6)

### Battery Monitoring
- Read battery % continuously in background
- Announce "battery low" at 20%
- Automatically dock at 15%
- Resume behaviour after charging complete
- Display battery on any future screen

### Docking Behaviour
- Detect dock with Roomba's built-in IR sensors
- Implement OI `SEEK_DOCK` + status polling
- Return to dock when idle > 10 minutes
- Return to dock on command

### Crash Recovery
- Monitor serial port health in background thread
- Auto-reconnect if USB cable wiggled
- Retry with backoff (1s, 2s, 5s, give up)
- Alert via TTS "Connection lost. Reconnecting."

### Web Status Dashboard
- Tiny Flask server on port 5000
- Shows: current behaviour, battery, vision state, last AI response
- Camera feed thumbnail (MJPEG stream)
- Manual command buttons

---

## Tier 2 — Medium-Term

### HuskyLens AI Camera
- Replace or supplement the USB webcam with a HuskyLens AI camera module
- HuskyLens runs object detection, face recognition, and line tracking **on-device**
  — offloads vision work entirely from the host CPU
- Communicates via I2C or UART — easy to wire into the existing serial stack
- Built-in modes useful for R-7:
  - **Face Recognition** — identify and remember specific people without heavy CV libs
  - **Object Tracking** — lock onto a person and track them smoothly
  - **Object Classification** — recognise common objects in the environment
  - **Line Tracking** — follow tape on the floor for guided navigation
- Would allow vision to keep running even on lower-powered hardware (Pi Zero etc.)
- HuskyLens returns bounding boxes + IDs over serial — drop-in replacement for
  the HOG/MobileNet detection pipeline in `vision/person_detector.py`
- Cost: ~$35–50 (DFRobot)
- Companion library: `pip install huskylib` or use raw UART protocol

### ESP32 Head Movement
- R-7 gets a physical rotating/tilting head
- ESP32 receives serial commands from Pi
- Servo motor controls pan/tilt
- Head turns toward detected person
- Head tilts when confused / curious
- Nods when agreeing

### Emotion LED Eyes
- LED matrix or OLED displays as eyes
- Different expressions: happy, confused, scared, sleeping
- Blink randomly when idle
- Wide eyes on person detection
- X_X when bumping into things

### Droid Sound Pack
- R2-D2 style beep/whistle audio files
- Play through PC speaker (not Roomba speaker)
- Different sounds for different emotions/events
- Mix with TTS (beep + then speak)
- Startup boot sequence sound

### SLAM Mapping
- Map the room while roaming
- Know "I've been here before"
- Return to known locations
- Navigate around known obstacles
- Use `slam_toolbox` (ROS2) or `cartographer`

---

## Tier 3 — Long-Term / Advanced

### Object Memory
- Remember where objects are ("the chair is usually here")
- Avoid known obstacles proactively
- Say "Oh, the couch moved!"
- Persistent storage: SQLite or JSON file

### Room Understanding
- Label rooms ("kitchen", "living room")
- Navigate by room name: "go to the kitchen"
- Associate people with rooms
- Build a semantic map

### Multiple Personalities
- Switchable personality profiles via config
- "Serious mode" for when guests are over
- "Kid mode" — simpler, more playful
- "Night mode" — quieter, dimmer eyes, slower movement
- Switch via voice command or time of day

### Gesture Recognition
- Wave = greeting response
- Point = "look over there" / navigate to point
- Stop hand = halt immediately
- Arms raised = celebrate
- Uses MediaPipe pose estimation

### Person Memory
- Remember specific people by face
- Greet by name: "Hi [name]! Haven't seen you in 2 days."
- Face encoding stored in a local database
- Privacy mode: disable face memory on request

### Remote Mobile App
- React Native or Flutter app
- Live camera feed
- Manual drive controls
- See AI conversation history
- Toggle behaviours
- View maps

### Autonomous Decision Making
- Goal-oriented behaviour: "find a person", "explore new area"
- Decision trees or simple planning
- Learn from past behaviour (what worked, what didn't)
- Eventually: reinforcement learning for navigation

### Cleaning Mode Integration
- Use the Roomba's actual cleaning in autonomous mode
- Schedule cleaning when no people are home
- Resume follow-person after cleaning completes
- Report cleaning coverage area

### lidar Support
- Add a cheap 2D lidar (RPLIDAR A1, ~$100)
- Real obstacle detection instead of camera-based
- True SLAM with accurate maps
- Navigate in the dark

### Voice Recognition (Speaker ID)
- Recognize whose voice is speaking
- Different responses for different people
- Private mode: only respond to registered voices

### Emotional States
- Internal emotion model: happy, curious, bored, scared, sleepy
- Emotion shifts based on events:
  - Person found → happy
  - Stuck → frustrated
  - Long alone time → bored
  - Many bumps → scared
- Emotion affects speech and movement style
- Display emotion on LED eyes

### Multi-Robot Coordination
- Two R-7 droids in the same space
- Broadcast positions via local network
- Avoid each other
- Play together (follow-the-leader)

### ROS2 Migration
- Replace all managers with ROS2 nodes
- Use Nav2 for navigation
- Use RViz for visualization
- Enable SLAM + autonomous navigation
- Enable multi-robot coordination via DDS

---

## Wild Ideas (Just For Fun)

- **Party mode:** lights, random dancing movements, plays music
- **Guard mode:** detect and photograph intruders at night, send phone alert
- **Plant watering:** add a tiny water dispenser, water scheduled plants
- **Mail checker:** station near mailbox, announce "You have mail!"
- **Cat / pet tracking:** follow the cat instead of a person
- **AR overlay:** project droid "emotions" via overhead projector
- **R2-D2 cosplay shell:** full 3D-printed enclosure to look like R2
- **Force-push gag:** user waves hand, droid rolls backward
- **Hologram projector:** small pico projector, Princess Leia message style
