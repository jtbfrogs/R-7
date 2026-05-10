"""
behaviors/behavior_manager.py
──────────────────────────────
The behaviour state machine — the brain of the droid.

This is where all the subsystems come together and the droid decides
what to DO based on what it SEES and KNOWS.

State machine
──────────────
                    ┌─────────────────────────────────────────┐
                    │         IDLE (just started)             │
                    └────────────┬────────────────────────────┘
                                 │ startup() called
                    ┌────────────▼────────────────────────────┐
                    │         FREE_ROAM (default)             │◄──┐
                    └────────────┬────────────────────────────┘   │
         person detected        │               person lost > timeout
                    ┌────────────▼────────────────────────────┐   │
                    │         FOLLOW_PERSON                   │   │
                    └────────────┬────────────────────────────┘   │
         person lost             │                                 │
                    ┌────────────▼────────────────────────────┐   │
                    │         SEARCH_PERSON                   ├───┘
                    └─────────────────────────────────────────┘

Obstacle avoidance is a MODIFIER that interrupts any behaviour,
not a separate state.  When an obstacle is detected:
  1. Stop immediately
  2. Back up briefly
  3. Turn away
  4. Resume previous behaviour

Priority order (highest first)
────────────────────────────────
  1. Obstacle / bump   (ALWAYS interrupts)
  2. Follow person     (when person visible)
  3. Search person     (when person was recently seen)
  4. Free roam         (fallback)
"""

import time
import threading
import random
from enum import Enum, auto
from typing import Optional

from roomba.controller       import RoombaController
from vision.vision_manager   import VisionManager
from ai.personality          import Personality
from ai.ollama_client        import OllamaClient
from ai.context_builder      import build_context
from audio.tts_manager       import TTSManager
from utilities.logger        import get_logger
from utilities.helpers       import jitter, sleep_ms
from utilities.constants     import (
    SEARCH_TIMEOUT_SEC, SEARCH_SPIN_DURATION_SEC,
    ROAM_MIN_FORWARD_SEC, ROAM_MAX_FORWARD_SEC, ROAM_TURN_DURATION_SEC,
    OBSTACLE_BACKUP_SEC, OBSTACLE_TURN_SEC,
    FOLLOW_DISTANCE_THRESHOLD, DRIVE_TURN_SPEED,
)
from config.config_loader import get_config

log = get_logger(__name__)


class BehaviorState(Enum):
    IDLE          = auto()   # not started
    FREE_ROAM     = auto()   # wandering around
    FOLLOW_PERSON = auto()   # tracking a visible person
    SEARCH_PERSON = auto()   # looking for a lost person
    OBSTACLE      = auto()   # reacting to an obstacle (transient)
    DOCKING       = auto()   # driving to the dock
    STOPPED       = auto()   # intentionally stopped (command or shutdown)


class BehaviorManager:
    """
    Runs the droid's behaviour in a continuous loop.

    The behaviour loop runs at ~10 Hz.  Every iteration:
      1. Read latest vision state
      2. Check for obstacles/bumps
      3. Decide which behaviour to run
      4. Issue movement commands
      5. Trigger speech if appropriate

    Usage
    ─────
        bm = BehaviorManager(roomba, vision, tts)
        bm.start()
        # ... runs in background thread ...
        bm.stop()
    """

    def __init__(
        self,
        roomba:     RoombaController,
        vision:     VisionManager,
        tts:        TTSManager,
        personality: Personality,
        ai_client:  Optional[OllamaClient] = None,
    ):
        self._roomba     = roomba
        self._vision     = vision
        self._tts        = tts
        self._personality = personality
        self._ai         = ai_client

        self._cfg         = get_config()["behavior"]
        self._state       = BehaviorState.IDLE
        self._prev_state  = BehaviorState.IDLE
        self._running     = False
        self._thread:     Optional[threading.Thread] = None

        # Search mode tracking
        self._search_start_time: float = 0.0
        self._last_person_seen:  float = 0.0

        # Roam mode state
        self._roam_forward_until: float = 0.0
        self._roam_turn_until:    float = 0.0
        self._roam_turning:       bool  = False
        self._roam_turn_direction: int  = 1   # +1 = right, -1 = left

        # Thresholds from config
        self._search_timeout   = self._cfg.get("search_timeout_sec",   SEARCH_TIMEOUT_SEC)
        self._search_spin_dur  = self._cfg.get("search_spin_duration_sec", SEARCH_SPIN_DURATION_SEC)
        self._roam_min         = self._cfg.get("roam_min_forward_sec", ROAM_MIN_FORWARD_SEC)
        self._roam_max         = self._cfg.get("roam_max_forward_sec", ROAM_MAX_FORWARD_SEC)
        self._roam_turn_dur    = self._cfg.get("roam_turn_duration_sec", ROAM_TURN_DURATION_SEC)
        self._obs_backup       = self._cfg.get("obstacle_backup_sec",  OBSTACLE_BACKUP_SEC)
        self._obs_turn         = self._cfg.get("obstacle_turn_sec",    OBSTACLE_TURN_SEC)
        self._follow_stop_dist = get_config()["vision"].get("follow_stop_distance", FOLLOW_DISTANCE_THRESHOLD)

        # Bumper polling: reading sensors every tick hammers the serial bus.
        # Only query bumpers every BUMPER_POLL_EVERY ticks (every 500 ms at 10 Hz).
        self._bumper_poll_every = 5
        self._tick_count        = 0

        # Detection debounce: number of consecutive ticks with NO detection
        # required before leaving FOLLOW_PERSON → SEARCH_PERSON.
        # At 10 Hz, 8 ticks = 800 ms of continuous absence before we accept
        # that the person is really gone.  This stops the rapid FOLLOW↔SEARCH
        # thrashing caused by single-frame detection misses.
        self._no_detection_streak    = 0
        self._NO_DETECTION_THRESHOLD = 8   # ticks (≈ 800 ms)

        # AI speech: prompts for each behaviour transition event.
        # Mapped to situation keys so personality phrases are the fallback.
        self._AI_PROMPTS = {
            "person_found":      "You just spotted a person in front of you. Say a short, friendly greeting.",
            "person_lost":       "You lost sight of the person. Say you are going to look for them.",
            "roaming":           "You are exploring the room on your own. Say something curious.",
            "obstacle_detected": "You just bumped into something. React briefly.",
        }

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the behaviour loop in a background thread."""
        self._running = True
        self._state   = BehaviorState.FREE_ROAM
        self._thread  = threading.Thread(
            target  = self._behaviour_loop,
            daemon  = True,
            name    = "BehaviorThread",
        )
        self._thread.start()
        log.info("Behaviour manager started (initial state: FREE_ROAM)")

    def stop(self) -> None:
        """Stop the behaviour loop and halt the Roomba."""
        log.info("Behaviour manager stopping...")
        self._running = False
        if self._roomba.is_active:
            self._roomba.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        log.info("Behaviour manager stopped")

    @property
    def state(self) -> BehaviorState:
        return self._state

    def force_state(self, state: BehaviorState) -> None:
        """Override the current behaviour state (for manual control / testing)."""
        log.info("Behaviour state forced: %s → %s", self._state.name, state.name)
        self._prev_state = self._state
        self._state = state

    # ─── Main loop ───────────────────────────────────────────────────────────

    def _behaviour_loop(self) -> None:
        """The main 10 Hz behaviour loop."""
        log.debug("Behaviour loop started")
        loop_period = 0.1   # 10 Hz

        while self._running:
            loop_start = time.time()

            try:
                self._tick()
            except Exception as e:
                log.error("Behaviour loop error: %s", e, exc_info=True)
                self._roomba.stop()   # safe fallback

            # Maintain loop period
            elapsed = time.time() - loop_start
            sleep_time = max(0, loop_period - elapsed)
            time.sleep(sleep_time)

        log.debug("Behaviour loop ended")

    def _tick(self) -> None:
        """Single behaviour iteration — called every 100 ms."""
        self._tick_count += 1
        vision = self._vision.get_vision_state()
        now    = time.time()

        # ── 1. OBSTACLE CHECK (highest priority, throttled) ──────────────
        # Only poll bumpers every BUMPER_POLL_EVERY ticks to avoid flooding
        # the serial bus while the Roomba is executing drive commands.
        if self._tick_count % self._bumper_poll_every == 0:
            if self._check_obstacle(vision):
                return   # obstacle handling takes over

        # ── 2. UPDATE PERSON TRACKING ────────────────────────────────────
        # FIX: use any_target_detected (body OR face) not just person_detected.
        # HOG full-body detection frequently misses people who are sitting,
        # close to the camera, or partially out of frame.  The face cascade
        # is far more reliable indoors and should also trigger following.
        if vision.any_target_detected:
            self._last_person_seen = now

        # Debug log every 10 ticks (~1 s) so you can confirm live detection.
        # Run with --debug to see these lines in the terminal.
        if self._tick_count % 10 == 0:
            log.debug(
                "Tick %d | state=%-13s | body=%-5s face=%-5s any=%-5s | "
                "offset=%+.2f  fill=%.2f",
                self._tick_count,
                self._state.name,
                vision.person_detected,
                vision.face_detected,
                vision.any_target_detected,
                vision.target_x_offset,
                vision.target_fill,
            )

        # ── 3. STATE TRANSITIONS ─────────────────────────────────────────
        if self._state == BehaviorState.FREE_ROAM:
            if vision.any_target_detected:
                self._no_detection_streak = 0
                self._transition_to(BehaviorState.FOLLOW_PERSON, "person_found")

        elif self._state == BehaviorState.FOLLOW_PERSON:
            if not vision.any_target_detected:
                # Increment the consecutive-miss counter.
                # Only switch to SEARCH after NO_DETECTION_THRESHOLD consecutive
                # misses — prevents thrashing on a single dropped frame.
                self._no_detection_streak += 1
                if self._no_detection_streak >= self._NO_DETECTION_THRESHOLD:
                    self._search_start_time = now
                    self._no_detection_streak = 0
                    self._transition_to(BehaviorState.SEARCH_PERSON, "person_lost")
            else:
                # Person is visible — reset the miss counter
                self._no_detection_streak = 0

        elif self._state == BehaviorState.SEARCH_PERSON:
            if vision.any_target_detected:
                self._no_detection_streak = 0
                self._transition_to(BehaviorState.FOLLOW_PERSON, "person_found")
            elif (now - self._search_start_time) > self._search_timeout:
                log.info("Search timeout — returning to free roam")
                self._transition_to(BehaviorState.FREE_ROAM, "roaming")

        # ── 4. EXECUTE CURRENT BEHAVIOUR ─────────────────────────────────
        if self._state == BehaviorState.FREE_ROAM:
            self._do_free_roam(now)

        elif self._state == BehaviorState.FOLLOW_PERSON:
            self._do_follow_person(vision)

        elif self._state == BehaviorState.SEARCH_PERSON:
            self._do_search_person(now)

    # ─── Obstacle handling ────────────────────────────────────────────────────

    def _check_obstacle(self, vision) -> bool:
        """
        Check for obstacles via bumpers and vision.
        Returns True if an obstacle was found and handled.
        """
        # Check physical bump sensors
        bumpers = self._roomba.read_bumpers()
        if bumpers and (bumpers["left"] or bumpers["right"]):
            log.info("Bump sensor triggered! L=%s R=%s", bumpers["left"], bumpers["right"])
            self._handle_obstacle(bumpers.get("right", False))
            self._speak("obstacle_detected")
            return True

        return False

    def _handle_obstacle(self, obstacle_on_right: bool = False) -> None:
        """Back up and turn away from an obstacle."""
        prev_state = self._state
        self._state = BehaviorState.OBSTACLE

        log.info("Obstacle response: backing up (%.1fs) then turning", self._obs_backup)
        self._roomba.backward(self._obs_backup)

        # Turn away from the side the obstacle is on
        if obstacle_on_right:
            self._roomba.spin_left(0)
        else:
            self._roomba.spin_right(0)

        time.sleep(jitter(self._obs_turn, 0.2))
        self._roomba.stop()

        self._state = prev_state
        log.info("Obstacle handled — resuming %s", self._state.name)

    # ─── Follow person behaviour ──────────────────────────────────────────────

    def _do_follow_person(self, vision) -> None:
        """
        Drive toward the detected person, keeping them centred in frame.

        Logic:
          • If target fills > follow_stop_dist of frame → stop (close enough)
          • If target is to the left  → turn left while moving forward
          • If target is to the right → turn right while moving forward
          • If target is centred      → drive straight forward
        """
        offset = vision.target_x_offset   # -1.0 (left) to +1.0 (right)
        fill   = vision.target_fill       # 0.0 to 1.0

        # Stop if close enough
        if fill > self._follow_stop_dist:
            self._roomba.stop()
            return

        # Determine steering
        dead_zone = 0.15   # ignore tiny offsets — prevents constant jitter
        if offset < -dead_zone:
            # Target is left — turn left
            bias = min(abs(offset), 0.8)
            self._roomba.turn_left(0, bias)
        elif offset > dead_zone:
            # Target is right — turn right
            bias = min(abs(offset), 0.8)
            self._roomba.turn_right(0, bias)
        else:
            # Centred — drive forward
            self._roomba.forward(0)

    # ─── Search person behaviour ──────────────────────────────────────────────

    def _do_search_person(self, now: float) -> None:
        """
        Slowly spin to search for a lost person.
        Alternates spin direction every search_spin_duration_sec seconds.
        """
        elapsed_search = now - self._search_start_time
        # Determine spin phase
        phase = int(elapsed_search / self._search_spin_dur)
        if phase % 2 == 0:
            self._roomba.spin_left(0, speed=DRIVE_TURN_SPEED // 2)
        else:
            self._roomba.spin_right(0, speed=DRIVE_TURN_SPEED // 2)

    # ─── Free roam behaviour ──────────────────────────────────────────────────

    def _do_free_roam(self, now: float) -> None:
        """
        Autonomous wandering:
          • Drive forward for a random time
          • Turn a random amount
          • Repeat

        Feels curious and alive — not just straight lines.
        """
        if self._roam_turning:
            if now >= self._roam_turn_until:
                self._roam_turning = False
                self._roam_forward_until = now + jitter(
                    (self._roam_min + self._roam_max) / 2,
                    (self._roam_max - self._roam_min) / 2
                )
                self._roomba.forward(0)
        else:
            if now >= self._roam_forward_until:
                # Start a new turn
                self._roam_turning = True
                self._roam_turn_direction = random.choice([-1, 1])
                self._roam_turn_until = now + jitter(self._roam_turn_dur, 0.3)
                if self._roam_turn_direction > 0:
                    self._roomba.spin_right(0)
                else:
                    self._roomba.spin_left(0)
                # Occasionally say something while roaming
                if random.random() < 0.1 and self._personality.can_speak():
                    self._speak_bg("roaming")
            else:
                # Continue forward (send command again in case it was cleared)
                self._roomba.forward(0)

    # ─── State transitions ────────────────────────────────────────────────────

    def _transition_to(self, new_state: BehaviorState, speech_key: str) -> None:
        """
        Change state and optionally speak about it.
        Tries the AI first; falls back to canned personality phrases.
        """
        if new_state == self._state:
            return
        log.info("Behaviour: %s → %s", self._state.name, new_state.name)
        self._prev_state = self._state
        self._state      = new_state

        # Reset roam timers when entering free roam
        if new_state == BehaviorState.FREE_ROAM:
            self._roam_forward_until = time.time() + jitter(self._roam_min, 0.5)
            self._roam_turning = False

        # Speak the transition — prefer AI response, fall back to phrase
        if speech_key and self._personality.can_speak():
            prompt = self._AI_PROMPTS.get(speech_key)
            if prompt and self._ai:
                self._speak_ai_bg(prompt, speech_key)
            else:
                self._speak_bg(speech_key)

    # ─── Speech helpers ──────────────────────────────────────────────────────

    def _speak(self, situation: str) -> None:
        """Speak a personality phrase for the given situation (blocking-ish — queued)."""
        if self._personality.can_speak():
            phrase = self._personality.react(situation)
            self._tts.speak(phrase)
            self._personality.mark_spoke()

    def _speak_bg(self, situation: str) -> None:
        """Same as _speak but launches in a tiny background thread so it doesn't block."""
        t = threading.Thread(
            target=self._speak, args=(situation,), daemon=True
        )
        t.start()

    def _speak_ai(self, prompt: str, situation_fallback: str) -> None:
        """
        Ask the AI for a response and speak it (BLOCKING — call from a thread).
        Falls back to personality phrases if AI is unavailable or slow.
        """
        if self._ai and self._ai.is_available():
            try:
                vision   = self._vision.get_vision_state()
                context  = build_context(vision=vision, roomba=self._roomba)
                response = self._ai.ask(prompt, context)
                if response:
                    filtered = self._personality.filter_ai_response(response)
                    log.info("AI speaking: %s", filtered)
                    self._tts.speak(filtered)
                    self._personality.mark_spoke()
                    return
                else:
                    log.debug("AI returned empty response — using phrase fallback")
            except Exception as e:
                log.warning("AI speak error: %s — using phrase fallback", e)

        # Fallback to canned phrase
        self._speak(situation_fallback)

    def _speak_ai_bg(self, prompt: str, situation_fallback: str) -> None:
        """
        Non-blocking version of _speak_ai — launches in a daemon thread so
        the behaviour loop is not held up waiting for Ollama to respond.
        """
        t = threading.Thread(
            target  = self._speak_ai,
            args    = (prompt, situation_fallback),
            daemon  = True,
            name    = "AISpeak",
        )
        t.start()
