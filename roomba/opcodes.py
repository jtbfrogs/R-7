"""
roomba/opcodes.py
──────────────────
Human-readable wrappers that turn Roomba OI opcodes into actual byte
sequences ready to write to the serial port.

Every method returns `bytes` — nothing is sent here, only constructed.
Sending is the job of serial_manager.py.

This separation means you can unit-test command construction without
needing real hardware.

Reference: iRobot® Create® 2 Open Interface Specification (rev D)
           https://edu.irobot.com/learning-library/create-2-oi-spec
           (The 600 series uses the same protocol as Create 2)
"""

import struct
from utilities.constants import OI, RADIUS_SPIN_CW, RADIUS_SPIN_CCW, RADIUS_STRAIGHT
from utilities.helpers import pack_signed_16, clamp


# ─── Mode commands ────────────────────────────────────────────────────────────

def cmd_start() -> bytes:
    """
    OI opcode 128 — START.

    This MUST be the very first command sent after wakeup.
    It puts the Roomba into Passive mode and enables the OI.
    Until this is sent, all other commands are ignored.

    Returns
    -------
    b'\\x80'
    """
    return bytes([OI.START])


def cmd_safe() -> bytes:
    """
    OI opcode 131 — SAFE mode.

    In Safe mode:
      • You have full control of movement
      • Roomba automatically stops if it detects a cliff or wheel drop
      • This is the RECOMMENDED mode for normal operation

    Returns
    -------
    b'\\x83'
    """
    return bytes([OI.SAFE])


def cmd_full() -> bytes:
    """
    OI opcode 132 — FULL mode.

    In Full mode:
      • You have COMPLETE control — no safety stops
      • Roomba will drive off a table edge if you command it to
      • Only use this for testing, never for autonomous operation

    Returns
    -------
    b'\\x84'
    """
    return bytes([OI.FULL])


def cmd_passive() -> bytes:
    """
    OI opcode 128 — START puts Roomba back into Passive mode if already running.
    Sending START again from Safe/Full returns to Passive.

    Returns
    -------
    b'\\x80'
    """
    return bytes([OI.START])


def cmd_reset() -> bytes:
    """
    OI opcode 7 — Soft reset the Roomba OI.
    The Roomba will play its startup song and return to passive mode.
    Use this if the Roomba gets into a weird state.

    Returns
    -------
    b'\\x07'
    """
    return bytes([OI.RESET])


def cmd_power_off() -> bytes:
    """
    OI opcode 133 — Power down the Roomba.
    It will enter sleep mode.  Use wakeup() to bring it back.

    Returns
    -------
    b'\\x85'
    """
    return bytes([OI.POWER])


# ─── Movement commands ────────────────────────────────────────────────────────

def cmd_drive_direct(left_mm_s: int, right_mm_s: int) -> bytes:
    """
    OI opcode 145 — DRIVE DIRECT.

    This is the PREFERRED way to control movement because it specifies
    each wheel independently, making turns predictable.

    Velocity range: -500 to +500 mm/s
      • Positive = forward
      • Negative = backward

    Parameters
    ----------
    right_mm_s : right wheel velocity in mm/s
    left_mm_s  : left wheel velocity in mm/s

    Returns
    -------
    5 bytes: [145, right_high, right_low, left_high, left_low]

    Example
    -------
        cmd_drive_direct(200, 200)   # straight forward at 200 mm/s
        cmd_drive_direct(200, -200)  # spin clockwise in place
        cmd_drive_direct(0, 0)       # stop
    """
    right = int(clamp(right_mm_s, -500, 500))
    left  = int(clamp(left_mm_s,  -500, 500))
    return bytes([OI.DRIVE_DIRECT]) + pack_signed_16(right) + pack_signed_16(left)


def cmd_stop() -> bytes:
    """Stop both wheels immediately."""
    return cmd_drive_direct(0, 0)


def cmd_forward(speed: int = 300) -> bytes:
    """Drive straight forward at `speed` mm/s."""
    return cmd_drive_direct(speed, speed)


def cmd_backward(speed: int = 200) -> bytes:
    """Drive straight backward at `speed` mm/s (positive value = reverse)."""
    return cmd_drive_direct(-speed, -speed)


def cmd_spin_left(speed: int = 200) -> bytes:
    """
    Spin counter-clockwise (left) in place.
    Right wheel goes forward, left wheel goes backward.
    """
    return cmd_drive_direct(-speed, speed)


def cmd_spin_right(speed: int = 200) -> bytes:
    """
    Spin clockwise (right) in place.
    Left wheel goes forward, right wheel goes backward.
    """
    return cmd_drive_direct(speed, -speed)


def cmd_turn_left(forward_speed: int = 200, turn_bias: float = 0.5) -> bytes:
    """
    Gentle left curve: right wheel faster, left wheel slower.
    turn_bias 0.0 = straight ahead, 1.0 = sharp pivot.
    """
    right = int(forward_speed)
    left  = int(forward_speed * (1.0 - turn_bias))
    return cmd_drive_direct(right, left)


def cmd_turn_right(forward_speed: int = 200, turn_bias: float = 0.5) -> bytes:
    """
    Gentle right curve: left wheel faster, right wheel slower.
    """
    left  = int(forward_speed)
    right = int(forward_speed * (1.0 - turn_bias))
    return cmd_drive_direct(right, left)


# ─── Cleaning commands ────────────────────────────────────────────────────────

def cmd_clean() -> bytes:
    """OI opcode 135 — Start default clean cycle."""
    return bytes([OI.CLEAN])


def cmd_spot() -> bytes:
    """OI opcode 134 — Start Spot clean cycle."""
    return bytes([OI.SPOT])


def cmd_seek_dock() -> bytes:
    """OI opcode 143 — Drive to the dock autonomously."""
    return bytes([OI.SEEK_DOCK])


# ─── Sensor query commands ────────────────────────────────────────────────────

def cmd_sensor(packet_id: int) -> bytes:
    """
    OI opcode 142 — Request a single sensor packet.

    The Roomba will respond with the sensor data bytes.
    You must read the correct number of bytes from serial after sending this.

    Parameters
    ----------
    packet_id : one of the Sensor enum values from constants.py

    Example
    -------
        cmd_sensor(Sensor.OI_MODE)      # 1 byte response
        cmd_sensor(Sensor.VOLTAGE)      # 2 byte response
    """
    return bytes([OI.SENSORS, packet_id])


def cmd_query_list(packet_ids: list[int]) -> bytes:
    """
    OI opcode 149 — Request multiple sensor packets at once.
    More efficient than sending multiple cmd_sensor() requests.

    Parameters
    ----------
    packet_ids : list of Sensor enum values

    Example
    -------
        cmd_query_list([Sensor.OI_MODE, Sensor.VOLTAGE, Sensor.BATTERY_CHARGE])
    """
    n = len(packet_ids)
    return bytes([OI.QUERY_LIST, n] + list(packet_ids))


# ─── Song / beep commands ─────────────────────────────────────────────────────

def cmd_define_song(song_number: int, notes: list[tuple[int, int]]) -> bytes:
    """
    OI opcode 140 — Define a song.

    Parameters
    ----------
    song_number : 0–4 (Roomba stores up to 4 songs)
    notes       : list of (midi_note, duration_64ths) tuples
                  midi_note 31–127  (middle C = 60)
                  duration  1–255   (in 1/64th second increments;
                                     64 = 1 second, 32 = 0.5 seconds)

    Example
    -------
        # R2-D2 style beep sequence
        cmd_define_song(0, [(76, 16), (72, 8), (79, 16)])
    """
    payload = [OI.SONG, song_number, len(notes)]
    for midi, dur in notes:
        payload.extend([midi, dur])
    return bytes(payload)


def cmd_play_song(song_number: int) -> bytes:
    """
    OI opcode 141 — Play a previously defined song.

    Parameters
    ----------
    song_number : 0–4
    """
    return bytes([OI.PLAY, song_number])


def cmd_beep() -> bytes:
    """
    Define and immediately play a short droid beep.
    Returns the define + play bytes as a single sequence.
    Middle C (60) for 0.25 seconds, then a higher note.
    """
    define = cmd_define_song(0, [(72, 16), (76, 12), (79, 8)])
    play   = cmd_play_song(0)
    return define + play


def cmd_startup_song() -> bytes:
    """
    A cheerful little startup jingle.  Inspired by R2-D2 boot sounds.
    """
    notes = [(60, 8), (64, 8), (67, 8), (72, 16)]   # C-E-G-C
    define = cmd_define_song(1, notes)
    play   = cmd_play_song(1)
    return define + play
