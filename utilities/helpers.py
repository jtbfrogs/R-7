"""
utilities/helpers.py
─────────────────────
Small, stateless helper functions used across multiple modules.
Nothing here should depend on project subsystems — this is pure utility code.
"""

import time
import struct
import random
from typing import Iterable


# ─── Timing helpers ──────────────────────────────────────────────────────────

def sleep_ms(milliseconds: float) -> None:
    """Sleep for the given number of milliseconds. Cleaner than time.sleep(x/1000)."""
    time.sleep(milliseconds / 1000.0)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """
    Clamp `value` between `minimum` and `maximum`.

    Example
    -------
        speed = clamp(requested_speed, -500, 500)
    """
    return max(minimum, min(maximum, value))


def map_range(
    value: float,
    in_min: float, in_max: float,
    out_min: float, out_max: float,
) -> float:
    """
    Re-map `value` from one numeric range to another.

    Example
    -------
        # Convert a 0–100 percent value to a 0–500 mm/s wheel speed
        speed = map_range(throttle_pct, 0, 100, 0, 500)
    """
    if in_max == in_min:
        return out_min
    ratio = (value - in_min) / (in_max - in_min)
    return out_min + ratio * (out_max - out_min)


# ─── Byte packing helpers ────────────────────────────────────────────────────

def pack_signed_16(value: int) -> bytes:
    """
    Pack a signed 16-bit integer into 2 bytes, big-endian (high byte first).
    The Roomba DRIVE_DIRECT command requires this format.

    Example
    -------
        # 300 mm/s forward:  b'\\x01\\x2c'
        pack_signed_16(300)
    """
    return struct.pack(">h", int(clamp(value, -32768, 32767)))


def pack_unsigned_16(value: int) -> bytes:
    """Pack an unsigned 16-bit big-endian integer."""
    return struct.pack(">H", int(clamp(value, 0, 65535)))


def unpack_signed_16(data: bytes, offset: int = 0) -> int:
    """Unpack a signed 16-bit big-endian integer from `data` at `offset`."""
    return struct.unpack_from(">h", data, offset)[0]


def unpack_unsigned_16(data: bytes, offset: int = 0) -> int:
    """Unpack an unsigned 16-bit big-endian integer from `data` at `offset`."""
    return struct.unpack_from(">H", data, offset)[0]


def bytes_to_hex(data: bytes) -> str:
    """
    Convert bytes to a human-readable hex string for logging.

    Example
    -------
        bytes_to_hex(b'\\x83\\x00\\x90')  →  '83 00 90'
    """
    return " ".join(f"{b:02X}" for b in data)


# ─── Serial port discovery helpers ───────────────────────────────────────────

def find_serial_ports() -> list[str]:
    """
    Return a list of serial port device paths that exist on the system.
    Checks common Linux USB-serial patterns.

    Returns an empty list if none are found.
    """
    import glob
    patterns = [
        "/dev/ttyUSB*",    # FTDI / CH340 USB adapters
        "/dev/ttyACM*",    # Arduino-style CDC devices
        "/dev/ttyS*",      # native COM ports (rare on laptops)
        "/dev/tty.usb*",   # macOS fallback (dev environment)
    ]
    ports: list[str] = []
    for pattern in patterns:
        ports.extend(sorted(glob.glob(pattern)))
    return ports


def best_guess_roomba_port() -> str | None:
    """
    Heuristic: pick the lowest-numbered ttyUSB port as the Roomba.
    Returns None if no candidates found.
    """
    ports = [p for p in find_serial_ports() if "USB" in p or "ACM" in p]
    return ports[0] if ports else None


# ─── Text / speech helpers ───────────────────────────────────────────────────

def truncate_words(text: str, max_words: int) -> str:
    """
    Hard-truncate text to at most `max_words` words.
    Adds "..." if truncation happened.

    Example
    -------
        truncate_words("Hello there friend how are you", 4)
        → "Hello there friend how..."
    """
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def jitter(base: float, spread: float = 0.1) -> float:
    """
    Add a small random jitter to a value.  Used to make robot movements
    feel less mechanical and more alive.

    Example
    -------
        duration = jitter(2.0, 0.3)   # 2.0 ± up to 0.3 seconds
    """
    return base + random.uniform(-spread, spread)


def weighted_choice(options: list[str], weights: list[float] | None = None) -> str:
    """
    Pick a random string from `options` with optional weighting.

    Example
    -------
        phrase = weighted_choice(["Oh!", "Hmm.", "..."], [0.5, 0.3, 0.2])
    """
    return random.choices(options, weights=weights, k=1)[0]


# ─── Diagnostics helpers ─────────────────────────────────────────────────────

def check_import(module_name: str) -> bool:
    """
    Try importing a module and return True/False.
    Used by diagnostic scripts to check dependencies gracefully.
    """
    import importlib
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def format_check_result(label: str, ok: bool, detail: str = "") -> str:
    """
    Format a diagnostic check result line.

    Example
    -------
        format_check_result("Serial port", True, "/dev/ttyUSB0")
        →  "  ✓  Serial port        /dev/ttyUSB0"

        format_check_result("Serial port", False, "not found")
        →  "  ✗  Serial port        not found"
    """
    icon  = "✓" if ok else "✗"
    color = "\033[32m" if ok else "\033[31m"
    reset = "\033[0m"
    return f"  {color}{icon}{reset}  {label:<24} {detail}"
