"""
vision/vision_manager.py
─────────────────────────
Top-level vision coordinator.

Pulls everything together:
  • CameraManager  → provides raw frames
  • PersonDetector → detects people/faces
  • (future: ObstacleDetector, MotionTracker)

Exposes a simple interface to the behaviour system:
  • get_vision_state() → VisionState dataclass with everything the robot needs to decide

Runs in its own thread so vision processing never blocks the behaviour loop.
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from vision.camera_manager  import CameraManager
from vision.person_detector import PersonDetector, DetectionResult
from utilities.logger import get_logger
from config.config_loader import get_config

log = get_logger(__name__)


@dataclass
class VisionState:
    """
    Snapshot of everything the vision system currently sees.
    Shared with the behaviour system to make movement decisions.
    """
    timestamp:        float = field(default_factory=time.time)
    detection:        Optional[DetectionResult] = None
    person_detected:  bool  = False
    face_detected:    bool  = False
    # Horizontal offset of person from centre: -1.0 (left) to +1.0 (right)
    target_x_offset:  float = 0.0
    # How much of the frame the target fills (0.0–1.0)
    target_fill:      float = 0.0
    # Raw frame (for debug display / streaming)
    frame:            Optional[np.ndarray] = None
    frame_count:      int   = 0


class VisionManager:
    """
    Manages the vision pipeline in a background thread.

    Usage
    ─────
        vm = VisionManager()
        vm.start()

        while running:
            state = vm.get_vision_state()
            if state.person_detected:
                drive_toward(state.target_x_offset)

        vm.stop()
    """

    def __init__(self):
        self._cfg      = get_config()["vision"]
        self._camera   = CameraManager()
        self._detector = PersonDetector()
        self._state    = VisionState()
        self._lock     = threading.Lock()
        self._thread:  Optional[threading.Thread] = None
        self._running  = False

        # Debug window: show live camera feed with detections drawn on
        self._debug_display = False

    def start(self) -> bool:
        """Start camera and vision processing thread."""
        if not self._camera.start():
            log.error("Vision manager could not start — camera failed to open")
            return False

        self._running = True
        self._thread  = threading.Thread(
            target  = self._vision_loop,
            daemon  = True,
            name    = "VisionThread",
        )
        self._thread.start()
        log.info("Vision manager started")
        return True

    def stop(self) -> None:
        """Stop the vision thread and camera."""
        log.info("Stopping vision manager...")
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._camera.stop()
        log.info("Vision manager stopped")

    def get_vision_state(self) -> VisionState:
        """
        Return a copy of the latest vision state.
        Safe to call from any thread.
        """
        with self._lock:
            # Shallow copy is fine for a dataclass of scalars + one array ref
            return VisionState(
                timestamp       = self._state.timestamp,
                detection       = self._state.detection,
                person_detected = self._state.person_detected,
                face_detected   = self._state.face_detected,
                target_x_offset = self._state.target_x_offset,
                target_fill     = self._state.target_fill,
                frame           = self._state.frame,
                frame_count     = self._state.frame_count,
            )

    def enable_debug_display(self, enable: bool = True) -> None:
        """Show a live OpenCV window with detections drawn on the frame."""
        self._debug_display = enable
        if enable:
            log.info("Debug display enabled — press 'q' in the window to quit")

    @property
    def is_running(self) -> bool:
        return self._running

    # ─── Background thread ───────────────────────────────────────────────────

    def _vision_loop(self) -> None:
        """
        Main vision processing loop — runs in background thread.
        Continuously pulls frames and runs detection.
        """
        import cv2
        log.debug("Vision loop started")

        while self._running:
            frame = self._camera.get_latest_frame()

            if frame is None:
                # Camera not ready yet — wait briefly
                time.sleep(0.02)
                continue

            # Run detection (frame-skipping handled inside PersonDetector)
            detection = self._detector.detect(frame)

            # Build new vision state
            new_state = VisionState(
                detection       = detection,
                person_detected = detection.person_detected,
                face_detected   = detection.face_detected,
                target_x_offset = detection.target_x_offset(),
                target_fill     = detection.target_fill_ratio(),
                frame           = frame,
                frame_count     = self._camera.frame_count,
            )

            with self._lock:
                self._state = new_state

            # Optional debug display
            if self._debug_display:
                annotated = self._detector.draw_detections(frame, detection)
                cv2.imshow("R-7 Vision Debug", annotated)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    log.info("Debug display closed by user")
                    self._debug_display = False
                    cv2.destroyAllWindows()

            # ~30 iterations/sec target (actual detection slower due to frame-skipping)
            time.sleep(0.033)

        if self._debug_display:
            cv2.destroyAllWindows()
        log.debug("Vision loop ended")
