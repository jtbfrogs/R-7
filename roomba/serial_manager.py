"""
roomba/serial_manager.py
────────────────────────
Low-level serial port management for the Roomba UART connection.

This module owns ONE responsibility: reliably reading and writing bytes
to the serial port.  It does NOT know what the bytes mean — that is
the job of opcodes.py and controller.py.

IMPORTANT HARDWARE NOTES
─────────────────────────
The Roomba 650 uses a Mini-DIN 7-pin connector called the "Serial Port"
or "Cargo Bay" connector.  For a USB-UART adapter, you need:

  Roomba pin 3  →  RXD  (data INTO Roomba)
  Roomba pin 4  →  TXD  (data OUT of Roomba)
  Roomba pin 6  →  RTS  (Request To Send — used for WAKEUP)
  Roomba pin 7  →  GND  (common ground)

RTS WAKEUP BEHAVIOUR
─────────────────────
The Roomba 650 enters sleep mode after ~5 minutes of inactivity.
When asleep, it ignores all serial data.

To wake it up:
  1. Pull RTS LOW for ~150 ms
  2. Wait ~500 ms for the Roomba to boot its OI
  3. Send START opcode (128)
  4. Send SAFE or FULL opcode

RTS is ACTIVE LOW — pulling it low = asserting it = wakeup signal.
With pyserial:
  serial.setRTS(True)  → RTS pin goes LOW  (assert, wakeup)
  serial.setRTS(False) → RTS pin goes HIGH (deassert, normal)

BAUD RATE
──────────
Roomba 650 default: 115200 baud
After a POWER CYCLE the baud resets to 115200.
If your adapter negotiates a different baud, use cmd_baud() to change it.

TIMING
───────
The Roomba OI has minimum inter-command delays.
  • After START:       ≥ 200 ms before sending mode command
  • After mode change: ≥ 50 ms before movement commands
  • Between commands:  ≥ 15 ms (we use 30 ms for safety)

Violating these timings causes the Roomba to ignore commands silently.
"""

import time
import threading
from typing import Optional

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    raise ImportError(
        "pyserial is required.\n"
        "Install it with:  pip install pyserial"
    )

from utilities.logger import get_logger
from utilities.helpers import bytes_to_hex, sleep_ms, find_serial_ports, best_guess_roomba_port
from utilities.constants import (
    DEFAULT_BAUD_RATE, SERIAL_TIMEOUT, WAKEUP_PULSE_MS, WAKEUP_SETTLE_MS,
    MAX_RETRY_ATTEMPTS, COMMAND_DELAY_MS,
)
from config.config_loader import get_config

log = get_logger(__name__)


class SerialManager:
    """
    Manages the USB-UART serial connection to the Roomba 650.

    Thread-safety: uses an internal lock so commands from multiple threads
    (e.g. behaviour loop + camera callback) do not collide.

    Typical usage
    ─────────────
        sm = SerialManager()
        sm.connect()
        sm.send(b'\\x80')   # START
        sm.disconnect()
    """

    def __init__(self):
        self._port:   Optional[serial.Serial] = None
        self._lock:   threading.Lock = threading.Lock()
        self._connected: bool = False
        self._cfg = get_config()["roomba"]

        # Pull settings from config (with sensible fallbacks)
        self.baud_rate      = self._cfg.get("baud_rate",      DEFAULT_BAUD_RATE)
        self.serial_timeout = self._cfg.get("serial_timeout", SERIAL_TIMEOUT)
        self.max_retries    = self._cfg.get("max_retry_attempts", MAX_RETRY_ATTEMPTS)
        self.log_raw_bytes  = self._cfg.get("log_raw_bytes",  False)
        self.wakeup_pulse   = self._cfg.get("wakeup_pulse_ms",  WAKEUP_PULSE_MS)
        self.wakeup_settle  = self._cfg.get("wakeup_settle_ms", WAKEUP_SETTLE_MS)

        # The port name, resolved at connect() time
        self._port_name: str = ""

    # ─── Connection ──────────────────────────────────────────────────────────

    def connect(self, port: Optional[str] = None) -> bool:
        """
        Open the serial port and confirm connectivity.

        Parameters
        ----------
        port : device path e.g. "/dev/ttyUSB0"
               If None, the value from config is used.
               If config says "auto", we scan for USB-serial ports.

        Returns
        -------
        True  — port opened successfully
        False — failed (logged error, safe to retry)
        """
        if self._connected:
            log.warning("Already connected — disconnect first if you want to reconnect")
            return True

        # Resolve port name
        configured_port = port or self._cfg.get("port", "auto")
        if configured_port == "auto":
            configured_port = best_guess_roomba_port()
            if configured_port is None:
                log.error(
                    "No USB-serial ports found. "
                    "Check that your USB-UART adapter is plugged in.\n"
                    "  Available ports: %s",
                    find_serial_ports() or "none"
                )
                return False
            log.info("Auto-detected serial port: %s", configured_port)

        self._port_name = configured_port

        try:
            self._port = serial.Serial(
                port     = self._port_name,
                baudrate = self.baud_rate,
                bytesize = serial.EIGHTBITS,
                parity   = serial.PARITY_NONE,
                stopbits = serial.STOPBITS_ONE,
                timeout  = self.serial_timeout,
                # Do NOT enable RTS/CTS hardware flow control — we control RTS manually
                rtscts   = False,
                dsrdtr   = False,
            )
            self._connected = True
            log.info("Connected to Roomba on %s at %d baud", self._port_name, self.baud_rate)
            return True

        except serial.SerialException as e:
            log.error("Failed to open serial port %s: %s", self._port_name, e)
            log.error(
                "Troubleshooting:\n"
                "  • Is the USB adapter plugged in?\n"
                "  • Run: ls /dev/ttyUSB*\n"
                "  • Add yourself to the 'dialout' group: sudo usermod -aG dialout $USER\n"
                "  • Then log out and log back in"
            )
            return False

    def disconnect(self) -> None:
        """Close the serial port safely."""
        with self._lock:
            if self._port and self._port.is_open:
                self._port.close()
                log.info("Serial port %s closed", self._port_name)
            self._port = None
            self._connected = False

    @property
    def is_connected(self) -> bool:
        """True if the port is open and operational."""
        return self._connected and self._port is not None and self._port.is_open

    # ─── Wakeup ──────────────────────────────────────────────────────────────

    def wakeup(self) -> bool:
        """
        Wake the Roomba from sleep using the RTS pin.

        How it works
        ─────────────
        1. Assert RTS LOW  (serial.setRTS(True) = LOW on most adapters)
        2. Hold for wakeup_pulse_ms  (typically 150 ms)
        3. Deassert RTS HIGH
        4. Wait wakeup_settle_ms for Roomba to initialise (typically 500 ms)

        The Roomba will play a short startup sound if it was fully asleep.

        Returns
        -------
        True  — wakeup pulse sent
        False — not connected, cannot send pulse
        """
        if not self.is_connected:
            log.error("Cannot send wakeup: not connected")
            return False

        log.info("Sending wakeup pulse (RTS LOW for %d ms)...", self.wakeup_pulse)
        with self._lock:
            # Assert RTS LOW — wakes the Roomba
            self._port.setRTS(True)
            sleep_ms(self.wakeup_pulse)

            # Deassert — back to idle
            self._port.setRTS(False)

        log.debug("Wakeup pulse complete, waiting %d ms for Roomba to settle...", self.wakeup_settle)
        sleep_ms(self.wakeup_settle)
        log.info("Wakeup complete")
        return True

    # ─── Send / Receive ──────────────────────────────────────────────────────

    def send(self, data: bytes, description: str = "") -> bool:
        """
        Send bytes to the Roomba with retry logic.

        Parameters
        ----------
        data        : the bytes to send (built by opcodes.py)
        description : human-readable label for logging (e.g. "SAFE mode")

        Returns
        -------
        True  — bytes written successfully
        False — all retries failed

        Thread-safe: uses internal lock.
        """
        if not self.is_connected:
            log.error("Cannot send: not connected to Roomba")
            return False

        label = description or bytes_to_hex(data[:4])
        if self.log_raw_bytes:
            log.debug("TX [%s]: %s", label, bytes_to_hex(data))

        for attempt in range(1, self.max_retries + 1):
            try:
                with self._lock:
                    written = self._port.write(data)
                    self._port.flush()

                if written != len(data):
                    log.warning(
                        "Partial write on attempt %d/%d: sent %d of %d bytes",
                        attempt, self.max_retries, written, len(data)
                    )
                    sleep_ms(COMMAND_DELAY_MS * attempt)
                    continue

                # Success — log at debug level unless it's a movement command
                if self.log_raw_bytes or description:
                    log.debug("Sent [%s] (%d bytes)", label, written)
                return True

            except serial.SerialException as e:
                log.error(
                    "Serial write error on attempt %d/%d: %s",
                    attempt, self.max_retries, e
                )
                if attempt < self.max_retries:
                    sleep_ms(COMMAND_DELAY_MS * attempt * 2)  # back off
                else:
                    log.error("All %d write attempts failed for [%s]", self.max_retries, label)
                    self._handle_disconnect(e)

        return False

    def read(self, num_bytes: int, timeout_override: Optional[float] = None) -> Optional[bytes]:
        """
        Read exactly `num_bytes` from the Roomba.

        Parameters
        ----------
        num_bytes        : how many bytes to read
        timeout_override : optional per-call timeout in seconds

        Returns
        -------
        bytes if successful, None on timeout or error.

        Notes
        ─────
        Always call this IMMEDIATELY after sending a sensor request command.
        The Roomba sends sensor data within ~15 ms of receiving the query.
        If you wait too long, bytes may be lost or misaligned.
        """
        if not self.is_connected:
            log.error("Cannot read: not connected")
            return None

        try:
            with self._lock:
                if timeout_override is not None:
                    old_timeout = self._port.timeout
                    self._port.timeout = timeout_override

                data = self._port.read(num_bytes)

                if timeout_override is not None:
                    self._port.timeout = old_timeout

            if len(data) < num_bytes:
                log.warning(
                    "Read timeout: expected %d bytes, got %d",
                    num_bytes, len(data)
                )
                return None

            if self.log_raw_bytes:
                log.debug("RX (%d bytes): %s", len(data), bytes_to_hex(data))

            return data

        except serial.SerialException as e:
            log.error("Serial read error: %s", e)
            self._handle_disconnect(e)
            return None

    def flush_input(self) -> None:
        """Discard any stale bytes in the receive buffer."""
        if self.is_connected:
            with self._lock:
                self._port.reset_input_buffer()

    # ─── Error recovery ───────────────────────────────────────────────────────

    def _handle_disconnect(self, error: Exception) -> None:
        """
        Called when a serial error suggests the port has been disconnected.
        Marks connection as lost and logs recovery instructions.
        """
        log.error(
            "Serial port appears disconnected: %s\n"
            "  • Check USB cable\n"
            "  • Check that the adapter is still listed in: ls /dev/ttyUSB*\n"
            "  • Reconnect the cable and call connect() again",
            error
        )
        self._connected = False

    def get_port_info(self) -> dict:
        """Return a summary of the current connection state."""
        return {
            "port":      self._port_name,
            "baud_rate": self.baud_rate,
            "connected": self.is_connected,
            "timeout":   self.serial_timeout,
        }

    def list_available_ports(self) -> list[str]:
        """Convenience wrapper — list all serial ports on the system."""
        ports = []
        for p in serial.tools.list_ports.comports():
            ports.append(f"{p.device}  [{p.description}]")
        return ports
