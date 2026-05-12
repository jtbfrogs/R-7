"""
huskylens/huskylens_manager.py
───────────────────────────────
High-level HuskyLens 2 manager — drop-in replacement for the old VisionManager.

Runs a background thread that continuously polls the HuskyLens over UART and
maintains a shared HuskyLensState snapshot for the behaviour system to read.

Wiring (USB-UART adapter ↔ HuskyLens 2)
─────────────────────────────────────────
  USB-UART TXD  →  HuskyLens RXD
  USB-UART RXD  →  HuskyLens TXD
  USB-UART GND  →  HuskyLens GND
  USB-UART 3V3  →  HuskyLens 3V3   (or 5V pin if adapter is 5V)

HuskyLens settings (configure on the device before first use)
──────────────────────────────────────────────────────────────
  General Settings → Protocol Type  : UART
  General Settings → Baud Rate      : 9600  (match config below)
  Choose an algorithm from the home screen (e.g. Face Recognition)

Usage
─────
    hl = HuskyLensManager()
    if hl.start():
        state = hl.get_state()
        hl.stop()
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import serial
from huskylens.protocol import (
    HuskyProtocol,
    HuskyBlock,
    ALGO_IDS,
    ALGO_NAMES,
    ALGO_FACE_RECOGNITION,
    FRAME_W,
    FRAME_H,
)
from utilities.logger import get_logger
from utilities.helpers import find_serial_ports
from config.config_loader import get_config

log = get_logger(__name__)


@dataclass
class HuskyLensState:
    """
    Snapshot of what the HuskyLens currently detects.
    Mirrors the old VisionState interface so BehaviorManager needs no logic changes.
    """
    timestamp:       float = field(default_factory=time.time)
    algorithm:       str   = "face_recognition"
    person_detected: bool  = False   # any block present (body OR face)
    face_detected:   bool  = False   # specifically face_recognition algorithm active
    target_count:    int   = 0       # total number of detected objects
    target_id:       int   = 0       # ID of the primary (largest) target
    target_x_offset: float = 0.0    # -1.0 (left) … +1.0 (right)
    target_fill:     float = 0.0    # primary target width / frame width
    raw_blocks:      list  = field(default_factory=list)
    frame_count:     int   = 0

    @property
    def any_target_detected(self) -> bool:
        return self.person_detected or self.face_detected


# ── Manager ────────────────────────────────────────────────────────────────────

class HuskyLensManager:
    """
    Manages a HuskyLens 2 sensor connected over USB-UART.

    Thread-safe: get_state() may be called from any thread.
    The target_callback fires in the polling thread — keep it fast.
    """

    def __init__(self) -> None:
        cfg = get_config().get("huskylens", {})
        self._port_path: str       = cfg.get("port", "auto")
        self._baud:      int       = cfg.get("baud_rate", 9600)
        self._poll_hz:   int       = cfg.get("poll_hz", 10)
        self._algo_name: str       = cfg.get("algorithm", "face_recognition")

        self._ser:      Optional[serial.Serial]    = None
        self._proto:    Optional[HuskyProtocol]    = None
        self._state:    HuskyLensState             = HuskyLensState()
        self._lock:     threading.Lock             = threading.Lock()
        self._running:  bool                       = False
        self._thread:   Optional[threading.Thread] = None

        # Fires once when a target is acquired or lost (state change only)
        self._target_callback: Optional[Callable[[bool, HuskyLensState], None]] = None
        self._prev_detected:   bool = False

    # ─── Public lifecycle ──────────────────────────────────────────────────────

    def start(self) -> bool:
        """Open UART and start the polling thread. Returns True on success."""
        port = self._resolve_port()
        if not port:
            log.error("HuskyLens: no serial port found — check USB connection")
            return False

        log.info("HuskyLens: opening %s @ %d baud", port, self._baud)
        try:
            self._ser = serial.Serial(
                port,
                baudrate   = self._baud,
                timeout    = 0.5,
                write_timeout = 1.0,
            )
        except serial.SerialException as e:
            log.error("HuskyLens: serial open failed: %s", e)
            return False

        self._proto = HuskyProtocol(self._ser)
        time.sleep(0.3)   # let adapter settle after open

        # Handshake
        for attempt in range(3):
            if self._proto.knock():
                log.info("HuskyLens: handshake OK (attempt %d)", attempt + 1)
                break
            log.debug("HuskyLens: knock %d failed, retrying...", attempt + 1)
            time.sleep(0.4)
        else:
            log.error("HuskyLens: handshake failed — check wiring and baud rate in HuskyLens settings")
            self._ser.close()
            return False

        # Set algorithm
        algo_id = ALGO_IDS.get(self._algo_name, ALGO_FACE_RECOGNITION)
        if self._proto.set_algorithm(algo_id):
            log.info("HuskyLens: algorithm → %s", self._algo_name)
        else:
            log.warning("HuskyLens: could not set algorithm (device may still be starting)")

        self._running = True
        self._thread  = threading.Thread(
            target = self._poll_loop,
            daemon = True,
            name   = "HuskyLensThread",
        )
        self._thread.start()
        log.info("HuskyLens: polling at %d Hz", self._poll_hz)
        return True

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._ser and self._ser.is_open:
            self._ser.close()
        log.info("HuskyLens: stopped")

    # ─── State access ──────────────────────────────────────────────────────────

    def get_state(self) -> HuskyLensState:
        """Return a snapshot of the current detection state (thread-safe)."""
        with self._lock:
            return self._state

    def get_vision_state(self) -> HuskyLensState:
        """Alias for get_state() — backwards-compat with old VisionManager callers."""
        return self.get_state()

    # ─── Algorithm control ─────────────────────────────────────────────────────

    def set_algorithm(self, name: str) -> bool:
        """
        Switch the active algorithm by name.

        Valid names: face_recognition, object_tracking, object_recognition,
                     line_tracking, color_recognition, tag_recognition,
                     object_classification
        """
        if name not in ALGO_IDS:
            log.warning("HuskyLens: unknown algorithm %r", name)
            return False
        if not self._proto:
            log.warning("HuskyLens: not connected")
            return False
        algo_id = ALGO_IDS[name]
        if self._proto.set_algorithm(algo_id):
            self._algo_name = name
            with self._lock:
                self._state.algorithm = name
            log.info("HuskyLens: algorithm changed → %s", name)
            return True
        return False

    @property
    def current_algorithm(self) -> str:
        return self._algo_name

    # ─── Callbacks ────────────────────────────────────────────────────────────

    def set_target_callback(
        self,
        cb: Callable[[bool, "HuskyLensState"], None],
    ) -> None:
        """
        Register a callback that fires ONLY when target presence changes.
        Called with (target_detected: bool, state: HuskyLensState).
        Runs in the polling thread — keep it fast.
        """
        self._target_callback = cb

    # ─── Polling loop ──────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        period = 1.0 / max(1, self._poll_hz)
        while self._running:
            t0 = time.monotonic()
            try:
                self._poll_once()
            except Exception as e:
                log.error("HuskyLens poll error: %s", e)
            sleep = max(0.0, period - (time.monotonic() - t0))
            time.sleep(sleep)

    def _poll_once(self) -> None:
        if not self._proto:
            return

        blocks = self._proto.get_blocks()

        is_face   = self._algo_name == "face_recognition"
        detected  = len(blocks) > 0
        x_offset  = 0.0
        fill      = 0.0
        primary_id = 0

        if blocks:
            primary    = max(blocks, key=lambda b: b.w * b.h)
            primary_id = primary.id
            x_offset   = (primary.x - FRAME_W / 2.0) / (FRAME_W / 2.0)
            fill       = primary.w / FRAME_W
            x_offset   = max(-1.0, min(1.0, x_offset))
            fill       = max(0.0,  min(1.0, fill))

        with self._lock:
            fc = self._state.frame_count + 1
            self._state = HuskyLensState(
                timestamp       = time.time(),
                algorithm       = self._algo_name,
                person_detected = detected,
                face_detected   = detected and is_face,
                target_count    = len(blocks),
                target_id       = primary_id,
                target_x_offset = x_offset,
                target_fill     = fill,
                raw_blocks      = list(blocks),
                frame_count     = fc,
            )
            new_state = self._state

        # Fire callback only on state change (acquired / lost)
        if detected != self._prev_detected:
            self._prev_detected = detected
            if self._target_callback:
                try:
                    self._target_callback(detected, new_state)
                except Exception as e:
                    log.debug("HuskyLens target_callback error: %s", e)

    # ─── Port resolution ───────────────────────────────────────────────────────

    def _resolve_port(self) -> Optional[str]:
        if self._port_path != "auto":
            return self._port_path

        all_ports = find_serial_ports()
        if not all_ports:
            return None

        # Try to avoid the Roomba's port
        roomba_port = get_config()["roomba"].get("port", "auto")
        if roomba_port != "auto":
            candidates = [p for p in all_ports if p != roomba_port]
            if candidates:
                log.info("HuskyLens: auto-detected port %s (skipped Roomba port %s)",
                         candidates[0], roomba_port)
                return candidates[0]

        # Roomba is also auto — assume it takes the first port, try second
        if len(all_ports) >= 2:
            log.info("HuskyLens: auto-detected port %s (second available)", all_ports[1])
            return all_ports[1]

        log.info("HuskyLens: auto-detected port %s (only available)", all_ports[0])
        return all_ports[0]
