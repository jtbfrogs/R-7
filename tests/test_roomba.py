"""
tests/test_roomba.py
─────────────────────
Unit tests for Roomba opcodes and helper functions.
These tests run WITHOUT hardware — they only check byte construction.

Run with: pytest tests/
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import struct
import pytest
from roomba.opcodes import (
    cmd_start, cmd_safe, cmd_full, cmd_stop, cmd_forward, cmd_backward,
    cmd_spin_left, cmd_spin_right, cmd_drive_direct, cmd_beep,
)
from utilities.helpers import pack_signed_16, clamp, truncate_words, bytes_to_hex


class TestOpcodes:
    def test_start_opcode(self):
        assert cmd_start() == b'\x80'

    def test_safe_opcode(self):
        assert cmd_safe() == b'\x83'

    def test_full_opcode(self):
        assert cmd_full() == b'\x84'

    def test_stop_is_zero_velocity(self):
        data = cmd_stop()
        assert data[0] == 145   # DRIVE_DIRECT opcode
        right = struct.unpack(">h", data[1:3])[0]
        left  = struct.unpack(">h", data[3:5])[0]
        assert right == 0
        assert left  == 0

    def test_forward_positive_velocity(self):
        data = cmd_forward(300)
        right = struct.unpack(">h", data[1:3])[0]
        left  = struct.unpack(">h", data[3:5])[0]
        assert right > 0
        assert left  > 0
        assert right == left   # straight line

    def test_backward_negative_velocity(self):
        data = cmd_backward(200)
        right = struct.unpack(">h", data[1:3])[0]
        left  = struct.unpack(">h", data[3:5])[0]
        assert right < 0
        assert left  < 0

    def test_spin_left_wheels_opposite(self):
        data = cmd_spin_left(200)
        right = struct.unpack(">h", data[1:3])[0]
        left  = struct.unpack(">h", data[3:5])[0]
        assert right > 0    # right wheel forward
        assert left  < 0    # left wheel backward

    def test_spin_right_wheels_opposite(self):
        data = cmd_spin_right(200)
        right = struct.unpack(">h", data[1:3])[0]
        left  = struct.unpack(">h", data[3:5])[0]
        assert right < 0    # right wheel backward
        assert left  > 0    # left wheel forward

    def test_drive_direct_clamped_to_500(self):
        data = cmd_drive_direct(999, -999)
        right = struct.unpack(">h", data[1:3])[0]
        left  = struct.unpack(">h", data[3:5])[0]
        assert right <=  500
        assert left  >= -500

    def test_beep_has_correct_opcodes(self):
        data = cmd_beep()
        assert 140 in data   # SONG opcode
        assert 141 in data   # PLAY opcode


class TestHelpers:
    def test_clamp_within_range(self):
        assert clamp(5.0, 0.0, 10.0) == 5.0

    def test_clamp_below_min(self):
        assert clamp(-5.0, 0.0, 10.0) == 0.0

    def test_clamp_above_max(self):
        assert clamp(15.0, 0.0, 10.0) == 10.0

    def test_pack_signed_16_positive(self):
        result = pack_signed_16(300)
        assert struct.unpack(">h", result)[0] == 300

    def test_pack_signed_16_negative(self):
        result = pack_signed_16(-200)
        assert struct.unpack(">h", result)[0] == -200

    def test_bytes_to_hex(self):
        assert bytes_to_hex(b'\x80\x83') == "80 83"

    def test_truncate_words_short(self):
        assert truncate_words("Hello world", 10) == "Hello world"

    def test_truncate_words_long(self):
        result = truncate_words("one two three four five", 3)
        assert result == "one two three..."
        assert result.endswith("...")   # truncation marker present
        assert result.startswith("one two three")   # first 3 words preserved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
