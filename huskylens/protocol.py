"""
huskylens/protocol.py
──────────────────────
Low-level HuskyLens 2 UART binary protocol.

Packet format (all multi-byte integers are little-endian):
  [0x55][0xAA][0x11] [CMD] [LEN] [DATA × LEN] [CSUM]
  CSUM = (0x55 + 0xAA + 0x11 + CMD + LEN + sum(DATA)) & 0xFF

Response to REQUEST_BLOCKS:
  1 × RETURN_INFO  → tells you how many blocks follow
  N × RETURN_BLOCK → one per detected object

RETURN_INFO data (5 bytes):
  [nBlocks lo] [nBlocks hi]  (uint16 LE)
  [nArrows lo] [nArrows hi]  (uint16 LE)
  [frameNum]                 (uint8)

RETURN_BLOCK data (10 bytes):
  [x lo][x hi] [y lo][y hi] [w lo][w hi] [h lo][h hi] [id lo][id hi]
  All int16 LE.  x/y are centre coordinates (0–320, 0–240).
  id = 0 if not learned, 1–254 if trained.
"""

import struct
import time
from dataclasses import dataclass
from typing import Optional

import serial
from utilities.logger import get_logger

log = get_logger(__name__)

# ── Packet constants ──────────────────────────────────────────────────────────
HEADER = bytes([0x55, 0xAA, 0x11])

# ── Command bytes ─────────────────────────────────────────────────────────────
CMD_REQUEST_KNOCK          = 0x2C
CMD_REQUEST_ALGORITHM      = 0x2D
CMD_REQUEST_BLOCKS         = 0x21   # all detected block objects
CMD_REQUEST_LEARNED        = 0x23   # only trained/saved objects
CMD_RETURN_INFO            = 0x29   # result count header
CMD_RETURN_BLOCK           = 0x2A   # one detected block
CMD_RETURN_OK              = 0x2E   # success acknowledgement

# ── Algorithm IDs ─────────────────────────────────────────────────────────────
ALGO_FACE_RECOGNITION      = 0x01
ALGO_OBJECT_TRACKING       = 0x02
ALGO_OBJECT_RECOGNITION    = 0x03
ALGO_LINE_TRACKING         = 0x04
ALGO_COLOR_RECOGNITION     = 0x05
ALGO_TAG_RECOGNITION       = 0x06
ALGO_OBJECT_CLASSIFICATION = 0x07

ALGO_NAMES: dict[int, str] = {
    ALGO_FACE_RECOGNITION:     "face_recognition",
    ALGO_OBJECT_TRACKING:      "object_tracking",
    ALGO_OBJECT_RECOGNITION:   "object_recognition",
    ALGO_LINE_TRACKING:        "line_tracking",
    ALGO_COLOR_RECOGNITION:    "color_recognition",
    ALGO_TAG_RECOGNITION:      "tag_recognition",
    ALGO_OBJECT_CLASSIFICATION:"object_classification",
}
ALGO_IDS: dict[str, int] = {v: k for k, v in ALGO_NAMES.items()}

# HuskyLens internal coordinate space
FRAME_W = 320
FRAME_H = 240


@dataclass
class HuskyBlock:
    """One detected object returned by the HuskyLens."""
    x:  int   # centre X, 0–320
    y:  int   # centre Y, 0–240
    w:  int   # bounding-box width
    h:  int   # bounding-box height
    id: int   # object ID (0 = unlearned, 1–254 = trained)


# ── Packet builder ────────────────────────────────────────────────────────────

def _checksum(payload: bytes) -> int:
    return sum(payload) & 0xFF


def build_request(command: int, data: bytes = b"") -> bytes:
    body = HEADER + bytes([command, len(data)]) + data
    return body + bytes([_checksum(body)])


# ── Block parser ──────────────────────────────────────────────────────────────

def _parse_block(data: bytes) -> HuskyBlock:
    if len(data) < 10:
        return HuskyBlock(0, 0, 0, 0, 0)
    x, y, w, h, id_ = struct.unpack_from("<5h", data)
    return HuskyBlock(x, y, w, h, id_)


# ── Protocol handler ──────────────────────────────────────────────────────────

class HuskyProtocol:
    """
    Wraps raw serial I/O with the HuskyLens binary protocol.

    All public methods are synchronous (block until reply or timeout).
    Designed to be called from a single polling thread.
    """

    def __init__(self, ser: serial.Serial) -> None:
        self._s = ser

    def knock(self) -> bool:
        """Ping the HuskyLens. Returns True if it replies OK."""
        self._s.reset_input_buffer()
        self._s.write(build_request(CMD_REQUEST_KNOCK))
        pkt = self._recv(timeout=1.0)
        return pkt is not None and pkt[0] == CMD_RETURN_OK

    def set_algorithm(self, algo_id: int) -> bool:
        """Switch the active algorithm. Returns True on OK reply."""
        data = struct.pack("<H", algo_id)
        self._s.write(build_request(CMD_REQUEST_ALGORITHM, data))
        pkt = self._recv(timeout=2.0)
        return pkt is not None and pkt[0] == CMD_RETURN_OK

    def get_blocks(self) -> list[HuskyBlock]:
        """
        Request all currently detected block objects.
        Returns an empty list if nothing is detected or on timeout.
        """
        self._s.reset_input_buffer()
        self._s.write(build_request(CMD_REQUEST_BLOCKS))
        return self._read_block_response()

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _read_block_response(self) -> list[HuskyBlock]:
        """Read one RETURN_INFO + N × RETURN_BLOCK packets."""
        info = self._recv(timeout=0.4)
        if info is None or info[0] != CMD_RETURN_INFO:
            return []

        payload = info[1]
        if len(payload) < 4:
            return []

        n_blocks = struct.unpack_from("<H", payload, 0)[0]
        blocks: list[HuskyBlock] = []

        for _ in range(n_blocks):
            pkt = self._recv(timeout=0.25)
            if pkt and pkt[0] == CMD_RETURN_BLOCK:
                blocks.append(_parse_block(pkt[1]))

        return blocks

    def _recv(self, timeout: float = 0.5) -> Optional[tuple[int, bytes]]:
        """
        Read one complete packet from the wire.
        Syncs to the 3-byte header first, then reads command/len/data/checksum.
        Returns (command, data_bytes) or None on timeout or bad checksum.
        """
        deadline = time.monotonic() + timeout
        tail = bytearray()

        # ── Step 1: sync to header ────────────────────────────────────────────
        while time.monotonic() < deadline:
            b = self._s.read(1)
            if not b:
                continue
            tail.append(b[0])
            if len(tail) > 32:
                tail = tail[-32:]
            if len(tail) >= 3 and tail[-3:] == bytearray(HEADER):
                break
        else:
            log.debug("HuskyLens: header sync timeout")
            return None

        # ── Step 2: command + dataLen ─────────────────────────────────────────
        meta = self._s.read(2)
        if len(meta) < 2:
            log.debug("HuskyLens: short meta read")
            return None
        command  = meta[0]
        data_len = meta[1]

        # ── Step 3: data + checksum ───────────────────────────────────────────
        body = self._s.read(data_len + 1)
        if len(body) < data_len + 1:
            log.debug("HuskyLens: short body read (%d < %d)", len(body), data_len + 1)
            return None

        data     = body[:data_len]
        got_csum = body[data_len]
        exp_csum = _checksum(HEADER + bytes([command, data_len]) + data)

        if got_csum != exp_csum:
            log.debug("HuskyLens: bad checksum got=%02X exp=%02X", got_csum, exp_csum)
            return None

        return command, bytes(data)
