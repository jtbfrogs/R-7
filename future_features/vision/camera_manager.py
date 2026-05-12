"""
vision/camera_manager.py
─────────────────────────
Owns the webcam: opens it, reads frames, exposes them to the rest of the system.

Design decisions
────────────────
  • Runs in its OWN background thread so frame capture never blocks the main loop.
  • Detectors/trackers consume frames via get_latest_frame() — no blocking.
  • Frame rate is configurable; defaults to 30 fps but can be dropped for
    lower-power operation.
  • Thread-safe: uses a lock around the frame buffer.
"""

import time
import threading
from typing import Optional

try:
    import cv2
except ImportError:
    raise ImportError("opencv-python is required.  Install: pip install opencv-python")

import numpy as np
from utilities.logger import get_logger
from config.config_loader import get_config

log = get_logger(__name__)


class CameraManager:
    """
    Background webcam capture thread.

    Usage
    ─────
        cam = CameraManager()
        cam.start()

        while running:
            frame = cam.get_latest_frame()
            if frame is not None:
                process(frame)

        cam.stop()
    """

    def __init__(self):
        self._cfg       = get_config()["vision"]
        self._cap:      Optional[cv2.VideoCapture] = None
        self._frame:    Optional[np.ndarray] = None
        self._frame_count: int = 0
        self._lock      = threading.Lock()
        self._thread:   Optional[threading.Thread] = None
        self._running   = False

        # Config values
        self._index  = self._cfg.get("camera_index", 0)
        self._width  = self._cfg.get("width",  640)
        self._height = self._cfg.get("height", 480)
        self._fps    = self._cfg.get("fps",    30)

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> bool:
        """
        Open the camera and start the capture thread.

        Returns True on success, False if the camera could not be opened.
        """
        log.info("Opening camera (index=%d, %dx%d @ %dfps)...",
                 self._index, self._width, self._height, self._fps)

        self._cap = cv2.VideoCapture(self._index)

        if not self._cap.isOpened():
            log.error(
                "Could not open camera index %d.\n"
                "  • Check that the webcam is plugged in.\n"
                "  • Try: ls /dev/video*\n"
                "  • Try a different index: camera_index: 1 in config",
                self._index
            )
            return False

        # Request preferred resolution and fps
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS,          self._fps)

        # Read actual values (camera may not honour the request exactly)
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_f = self._cap.get(cv2.CAP_PROP_FPS)
        log.info("Camera opened: %dx%d @ %.1f fps", actual_w, actual_h, actual_f)

        # Start background capture thread
        self._running = True
        self._thread  = threading.Thread(target=self._capture_loop, daemon=True, name="CameraThread")
        self._thread.start()
        log.info("Camera capture thread started")
        return True

    def stop(self) -> None:
        """Stop the capture thread and release the camera."""
        log.info("Stopping camera...")
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._cap:
            self._cap.release()
            self._cap = None
        log.info("Camera released")

    # ─── Frame access ────────────────────────────────────────────────────────

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """
        Return the most recently captured frame, or None if no frame yet.

        This is NON-BLOCKING — it returns whatever frame was last captured.
        Call it as frequently as you like from the main loop.

        Returns
        -------
        numpy.ndarray (BGR, HxWx3) or None
        """
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    @property
    def frame_count(self) -> int:
        """Total number of frames captured since start()."""
        return self._frame_count

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def resolution(self) -> tuple[int, int]:
        """(width, height) of the camera stream."""
        return (self._width, self._height)

    # ─── Background thread ───────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        """
        Background loop — continuously reads frames from the camera.
        Runs in its own thread; do not call directly.
        """
        consecutive_failures = 0
        max_failures = 10

        while self._running:
            ret, frame = self._cap.read()

            if not ret or frame is None:
                consecutive_failures += 1
                log.warning("Camera read failed (%d/%d)", consecutive_failures, max_failures)
                if consecutive_failures >= max_failures:
                    log.error("Too many consecutive camera read failures — stopping camera thread")
                    self._running = False
                    break
                time.sleep(0.05)
                continue

            consecutive_failures = 0

            with self._lock:
                self._frame = frame
                self._frame_count += 1

            # Throttle the capture loop slightly to avoid spinning at 100% CPU
            # when the camera FPS is lower than the loop speed
            time.sleep(0.005)

        log.info("Camera capture loop ended (captured %d frames)", self._frame_count)
