"""
roomba/controller.py
──────────────────────
The primary interface between the rest of the project and the Roomba.

All code that wants to control the Roomba should import RoombaController.
No other module should import serial_manager or opcodes directly.

Responsibilities
────────────────
  • Connect and disconnect
  • Wake up the Roomba
  • Set operating mode (passive / safe / full)
  • Send movement commands
  • Read sensor data
  • Log all state changes
  • Recover from errors

State machine
─────────────
  DISCONNECTED
      ↓  connect()
  CONNECTED (passive, OI not started)
      ↓  startup()
  PASSIVE
      ↓  set_safe_mode()
  SAFE           ← normal operating mode
      ↓  set_full_mode()
  FULL           ← testing only
"""

import time
import threading
from enum import Enum, auto
from typing import Optional

from roomba.serial_manager import SerialManager
from roomba.opcodes import (
    cmd_start, cmd_safe, cmd_full, cmd_passive, cmd_reset,
    cmd_drive_direct, cmd_stop, cmd_forward, cmd_backward,
    cmd_spin_left, cmd_spin_right, cmd_turn_left, cmd_turn_right,
    cmd_clean, cmd_spot, cmd_seek_dock, cmd_sensor, cmd_query_list,
    cmd_beep, cmd_startup_song, cmd_power_off,
)
from utilities.constants import (
    OIMode, Sensor, STARTUP_DELAY_MS, MODE_CHANGE_DELAY_MS,
    COMMAND_DELAY_MS, DRIVE_MAX_SPEED,
)
from utilities.helpers import sleep_ms, clamp
from utilities.logger import get_logger
from config.config_loader import get_config

log = get_logger(__name__)


class ControllerState(Enum):
    """High-level connection/mode state of the controller."""
    DISCONNECTED = auto()
    CONNECTED    = auto()   # serial open, OI not started
    PASSIVE      = auto()   # OI started, passive mode
    SAFE         = auto()   # safe mode — normal operation
    FULL         = auto()   # full mode — no safety stops


class RoombaController:
    """
    High-level Roomba controller.

    Usage
    ─────
        roomba = RoombaController()
        if roomba.startup():
            roomba.forward(1.5)      # drive forward for 1.5 seconds
            roomba.spin_left(90)     # roughly 90° left turn
            roomba.beep()
            roomba.stop()
            roomba.shutdown()
    """

    def __init__(self):
        self._serial    = SerialManager()
        self._state     = ControllerState.DISCONNECTED
        self._cfg       = get_config()
        self._lock      = threading.Lock()

        # Cached sensor values (updated on read_sensors())
        self._oi_mode:      int = 0
        self._voltage_mv:   int = 0
        self._battery_pct:  float = 0.0
        self._bump_left:    bool = False
        self._bump_right:   bool = False
        self._cliff_left:   bool = False
        self._cliff_right:  bool = False

    # ─── Startup / shutdown ──────────────────────────────────────────────────

    def startup(self, port: Optional[str] = None) -> bool:
        """
        Full startup sequence:
          1. Open serial port
          2. Send RTS wakeup pulse
          3. Send START opcode
          4. Enter Safe mode

        This is the ONLY correct way to start using the Roomba.
        Calling movement commands before startup() will fail.

        Returns
        -------
        True if fully started and in Safe mode, False on any failure.
        """
        log.info("=== Roomba startup sequence ===")

        # Step 1: open serial port
        if not self._serial.connect(port):
            log.error("Startup failed: cannot open serial port")
            return False
        self._state = ControllerState.CONNECTED

        # Step 2: RTS wakeup pulse
        log.info("Sending wakeup pulse...")
        if not self._serial.wakeup():
            log.error("Startup failed: wakeup pulse error")
            return False

        # Step 3: send START opcode — enables the OI
        log.info("Sending START opcode...")
        if not self._send(cmd_start(), "START"):
            log.error("Startup failed: could not send START")
            return False
        sleep_ms(STARTUP_DELAY_MS)
        self._state = ControllerState.PASSIVE

        # Step 4: enter configured mode
        startup_mode = self._cfg["roomba"].get("startup_mode", "safe")
        if startup_mode == "full":
            success = self._enter_full_mode()
        else:
            success = self._enter_safe_mode()

        if not success:
            log.error("Startup failed: could not enter %s mode", startup_mode)
            return False

        # Optional startup song
        log.info("Playing startup beep...")
        self._send(cmd_startup_song(), "startup song")
        sleep_ms(1500)   # let the song finish

        log.info("=== Roomba startup complete — state: %s ===", self._state.name)
        return True

    def shutdown(self) -> None:
        """
        Gracefully stop the Roomba and close the serial port.
        Always call this when done.
        """
        log.info("Shutting down Roomba...")
        if self._state not in (ControllerState.DISCONNECTED, ControllerState.CONNECTED):
            self.stop()
            sleep_ms(200)
        self._serial.disconnect()
        self._state = ControllerState.DISCONNECTED
        log.info("Roomba disconnected")

    def reconnect(self) -> bool:
        """
        Attempt to reconnect if the serial port was lost.
        Useful if the USB cable was briefly unplugged.
        """
        log.warning("Attempting reconnect...")
        self.shutdown()
        time.sleep(1.0)
        return self.startup()

    # ─── Mode control ────────────────────────────────────────────────────────

    def _enter_safe_mode(self) -> bool:
        """Switch to Safe mode (recommended for normal operation)."""
        log.info("Entering SAFE mode...")
        if not self._send(cmd_safe(), "SAFE"):
            return False
        sleep_ms(MODE_CHANGE_DELAY_MS)
        self._state = ControllerState.SAFE
        log.info("Mode: SAFE")
        return True

    def _enter_full_mode(self) -> bool:
        """Switch to Full mode (no safety stops — use with caution)."""
        log.warning("Entering FULL mode — safety stops disabled!")
        if not self._send(cmd_full(), "FULL"):
            return False
        sleep_ms(MODE_CHANGE_DELAY_MS)
        self._state = ControllerState.FULL
        log.info("Mode: FULL")
        return True

    def set_safe_mode(self) -> bool:
        """Public method to switch to Safe mode from anywhere."""
        return self._enter_safe_mode()

    def set_full_mode(self) -> bool:
        """Public method to switch to Full mode."""
        return self._enter_full_mode()

    # ─── Movement ────────────────────────────────────────────────────────────

    def _require_active(self) -> bool:
        """Check that we're in a mode that accepts movement commands."""
        if self._state in (ControllerState.SAFE, ControllerState.FULL):
            return True
        log.warning(
            "Movement command ignored — not in SAFE or FULL mode (state: %s). "
            "Call startup() first.",
            self._state.name,
        )
        return False

    def drive(self, left_mm_s: int, right_mm_s: int) -> bool:
        """
        Direct wheel velocity control.

        Parameters
        ----------
        left_mm_s  : left wheel speed  (-500 to +500 mm/s)
        right_mm_s : right wheel speed (-500 to +500 mm/s)
        """
        if not self._require_active():
            return False
        # Clamp to safe maximum from config
        max_spd = self._cfg.get("drive", {}).get("max_speed", DRIVE_MAX_SPEED)
        left  = int(clamp(left_mm_s,  -max_spd, max_spd))
        right = int(clamp(right_mm_s, -max_spd, max_spd))
        return self._send(cmd_drive_direct(left, right))

    def stop(self) -> bool:
        """Stop both wheels immediately."""
        if not self._require_active():
            return False
        return self._send(cmd_stop(), "STOP")

    def forward(self, duration_sec: float = 0.0, speed: Optional[int] = None) -> bool:
        """
        Drive forward.

        Parameters
        ----------
        duration_sec : if > 0, drive for this many seconds then stop.
                       if 0 (default), drive indefinitely until stop() is called.
        speed        : mm/s (defaults to config value)
        """
        if not self._require_active():
            return False
        spd = speed or self._cfg.get("drive", {}).get("forward_speed", 300)
        ok  = self._send(cmd_forward(spd), "FORWARD")
        if duration_sec > 0:
            time.sleep(duration_sec)
            self.stop()
        return ok

    def backward(self, duration_sec: float = 0.0, speed: Optional[int] = None) -> bool:
        """Drive backward (speed is positive, direction reversed internally)."""
        if not self._require_active():
            return False
        spd = speed or self._cfg.get("drive", {}).get("backward_speed", 200)
        ok  = self._send(cmd_backward(spd), "BACKWARD")
        if duration_sec > 0:
            time.sleep(duration_sec)
            self.stop()
        return ok

    def spin_left(self, degrees: float = 90, speed: Optional[int] = None) -> bool:
        """
        Spin left (counter-clockwise).

        If `degrees` is given, calculate approximate duration from speed.
        Accuracy depends on surface/battery — use as a rough guide.

        NOTE: For precise turns, use encoders (future feature).
        """
        if not self._require_active():
            return False
        spd = speed or self._cfg.get("drive", {}).get("turn_speed", 200)
        ok  = self._send(cmd_spin_left(spd), "SPIN LEFT")

        if degrees > 0:
            # Rough approximation: Roomba 650 wheelbase ~235mm
            # circumference of rotation circle: π × 235 = ~738 mm
            # at speed `spd` for each wheel, robot turns at ~spd/117.5 rad/s
            duration = (degrees / 360.0) * (235.0 * 3.14159) / spd
            time.sleep(duration)
            self.stop()

        return ok

    def spin_right(self, degrees: float = 90, speed: Optional[int] = None) -> bool:
        """Spin right (clockwise). See spin_left for notes."""
        if not self._require_active():
            return False
        spd = speed or self._cfg.get("drive", {}).get("turn_speed", 200)
        ok  = self._send(cmd_spin_right(spd), "SPIN RIGHT")
        if degrees > 0:
            duration = (degrees / 360.0) * (235.0 * 3.14159) / spd
            time.sleep(duration)
            self.stop()
        return ok

    def turn_left(self, duration_sec: float = 0.0, bias: float = 0.5) -> bool:
        """Gentle left curve (not a point turn)."""
        if not self._require_active():
            return False
        spd = self._cfg.get("drive", {}).get("forward_speed", 300)
        ok  = self._send(cmd_turn_left(spd, bias), "TURN LEFT")
        if duration_sec > 0:
            time.sleep(duration_sec)
            self.stop()
        return ok

    def turn_right(self, duration_sec: float = 0.0, bias: float = 0.5) -> bool:
        """Gentle right curve (not a point turn)."""
        if not self._require_active():
            return False
        spd = self._cfg.get("drive", {}).get("forward_speed", 300)
        ok  = self._send(cmd_turn_right(spd, bias), "TURN RIGHT")
        if duration_sec > 0:
            time.sleep(duration_sec)
            self.stop()
        return ok

    # ─── Cleaning / docking ───────────────────────────────────────────────────

    def clean(self) -> bool:
        """Start a cleaning cycle (Roomba takes control)."""
        log.info("Starting clean cycle")
        return self._send(cmd_clean(), "CLEAN")

    def spot_clean(self) -> bool:
        """Start a spot clean cycle."""
        return self._send(cmd_spot(), "SPOT CLEAN")

    def dock(self) -> bool:
        """
        Tell the Roomba to find and drive to its dock.
        The Roomba handles this autonomously using its IR sensors.
        """
        log.info("Seeking dock...")
        return self._send(cmd_seek_dock(), "SEEK DOCK")

    def power_off(self) -> bool:
        """Put the Roomba into sleep/power-off state."""
        self.stop()
        return self._send(cmd_power_off(), "POWER OFF")

    # ─── Sensors ─────────────────────────────────────────────────────────────

    def read_oi_mode(self) -> Optional[int]:
        """
        Read the current OI mode from the Roomba.

        Returns
        -------
        int: 0=off, 1=passive, 2=safe, 3=full
        None on failure

        This is useful for VERIFYING that mode changes actually took effect.
        """
        self._send(cmd_sensor(Sensor.OI_MODE), "sensor:OI_MODE")
        sleep_ms(30)
        data = self._serial.read(1)
        if data is None:
            log.warning("No response to OI_MODE sensor query")
            return None
        mode = data[0]
        mode_names = {0: "OFF", 1: "PASSIVE", 2: "SAFE", 3: "FULL"}
        log.debug("OI mode reported by Roomba: %s (%d)", mode_names.get(mode, "?"), mode)
        return mode

    def read_battery(self) -> Optional[dict]:
        """
        Read battery voltage, charge, and capacity.

        Returns
        -------
        dict: {"voltage_mv": int, "charge_mah": int, "capacity_mah": int, "pct": float}
        None on failure
        """
        # Request voltage, charge, and capacity in one query
        self._send(
            cmd_query_list([Sensor.VOLTAGE, Sensor.BATTERY_CHARGE, Sensor.BATTERY_CAPACITY]),
            "battery query"
        )
        sleep_ms(50)
        data = self._serial.read(6)   # 2 + 2 + 2 bytes
        if data is None or len(data) < 6:
            log.warning("Battery read failed")
            return None

        from utilities.helpers import unpack_unsigned_16
        voltage  = unpack_unsigned_16(data, 0)
        charge   = unpack_unsigned_16(data, 2)
        capacity = unpack_unsigned_16(data, 4)
        pct      = (charge / capacity * 100) if capacity > 0 else 0.0

        self._voltage_mv  = voltage
        self._battery_pct = pct

        result = {
            "voltage_mv":   voltage,
            "charge_mah":   charge,
            "capacity_mah": capacity,
            "pct":          round(pct, 1),
        }
        log.info("Battery: %.1f%% (%d mV, %d/%d mAh)", pct, voltage, charge, capacity)
        return result

    def read_bumpers(self) -> Optional[dict]:
        """
        Read bump sensor state.

        Returns
        -------
        dict: {"left": bool, "right": bool}
        """
        self._send(cmd_sensor(Sensor.BUMPS_WHEELDROPS), "bumper query")
        sleep_ms(30)
        data = self._serial.read(1)
        if data is None:
            return None
        b = data[0]
        left  = bool(b & 0x02)   # bit 1
        right = bool(b & 0x01)   # bit 0
        self._bump_left  = left
        self._bump_right = right
        return {"left": left, "right": right}

    # ─── Sounds ──────────────────────────────────────────────────────────────

    def beep(self) -> bool:
        """Play a short droid beep through the Roomba's built-in speaker."""
        return self._send(cmd_beep(), "BEEP")

    # ─── Status ──────────────────────────────────────────────────────────────

    @property
    def state(self) -> ControllerState:
        return self._state

    @property
    def is_active(self) -> bool:
        """True if in SAFE or FULL mode (ready for movement commands)."""
        return self._state in (ControllerState.SAFE, ControllerState.FULL)

    @property
    def is_connected(self) -> bool:
        return self._serial.is_connected

    def get_status(self) -> dict:
        """Return a summary dict of current controller state."""
        return {
            "state":       self._state.name,
            "connected":   self.is_connected,
            "battery_pct": self._battery_pct,
            "voltage_mv":  self._voltage_mv,
            "bump_left":   self._bump_left,
            "bump_right":  self._bump_right,
        }

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _send(self, data: bytes, description: str = "") -> bool:
        """Internal send wrapper — adds inter-command delay."""
        ok = self._serial.send(data, description)
        sleep_ms(COMMAND_DELAY_MS)
        return ok
