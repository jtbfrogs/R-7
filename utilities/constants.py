"""
utilities/constants.py
─────────────────────
Central location for every magic number, string, and enum used across
the project.  If you need to change a value, change it HERE — not buried
inside five different source files.

Design rule: no raw numbers or strings scattered in business logic.
"""

from enum import IntEnum, auto

# ─── Project metadata ────────────────────────────────────────────────────────
PROJECT_NAME    = "R-7 Droid"
PROJECT_VERSION = "0.1.0"

# ─── Roomba Open Interface opcodes ───────────────────────────────────────────
# Full reference: iRobot® Create® 2 Open Interface (OI) Specification
# (also applies to Roomba 600 series)
class OI(IntEnum):
    """Every OI opcode the project uses, named for readability."""
    START        = 128   # Begin OI session; Roomba enters Passive mode
    BAUD         = 129   # Change baud rate (rarely needed)
    SAFE         = 131   # Enter Safe mode  — Roomba stops on cliff/wheeldrop
    FULL         = 132   # Enter Full mode  — no safety stops (be careful!)
    POWER        = 133   # Power off / enter sleep
    SPOT         = 134   # Start Spot-clean cycle
    CLEAN        = 135   # Start default clean cycle
    MAX          = 136   # Start Max-time clean cycle
    DRIVE        = 137   # Drive with radius (velocity, radius) — 4 bytes
    MOTORS       = 138   # Control brush/vacuum motors
    LEDS         = 139   # Control LEDs
    SONG         = 140   # Define a song
    PLAY         = 141   # Play a previously defined song
    SENSORS      = 142   # Request a single sensor packet
    SEEK_DOCK    = 143   # Drive to dock
    DRIVE_DIRECT = 145   # Independent wheel velocities — preferred for control
    DRIVE_PWM    = 146   # Raw PWM wheel control
    QUERY_LIST   = 149   # Request multiple sensor packets at once
    RESET        = 7     # Soft-reset the OI (same as holding Clean 10 s)
    STOP_OI      = 173   # Stop OI and return to non-OI mode

# ─── Roomba sensor packet IDs ─────────────────────────────────────────────────
class Sensor(IntEnum):
    """Sensor packet IDs used in SENSORS / QUERY_LIST commands."""
    BUMPS_WHEELDROPS   = 7    # 1 byte — bit-field
    WALL               = 8    # 1 byte — bool
    CLIFF_LEFT         = 9    # 1 byte — bool
    CLIFF_FRONT_LEFT   = 10
    CLIFF_FRONT_RIGHT  = 11
    CLIFF_RIGHT        = 12
    VIRTUAL_WALL       = 13
    OVERCURRENTS       = 14
    DIRT_DETECT        = 15
    IR_OMNI            = 17
    BUTTONS            = 18
    DISTANCE           = 19   # 2 bytes — signed mm since last request
    ANGLE              = 20   # 2 bytes — signed degrees since last request
    CHARGING_STATE     = 21
    VOLTAGE            = 22   # 2 bytes — mV
    CURRENT            = 23   # 2 bytes — mA signed
    TEMPERATURE        = 24   # 1 byte  — °C signed
    BATTERY_CHARGE     = 25   # 2 bytes — mAh
    BATTERY_CAPACITY   = 26   # 2 bytes — mAh
    OI_MODE            = 35   # 1 byte  — 0=off 1=passive 2=safe 3=full

# ─── Drive constants ──────────────────────────────────────────────────────────
# Roomba DRIVE_DIRECT accepts signed 16-bit mm/s for each wheel.
# Safe range: -500 to +500 mm/s
DRIVE_MAX_SPEED     =  400   # mm/s  — comfortable cruise speed
DRIVE_TURN_SPEED    =  200   # mm/s  — speed of each wheel during a point-turn
DRIVE_SEARCH_SPEED  =  150   # mm/s  — slow spin during person-search mode
DRIVE_STOP          =    0   # mm/s  — full stop

# Special DRIVE radius values
RADIUS_STRAIGHT     =  0x8000  # Drive straight (32768 — special value)
RADIUS_SPIN_CW      = -1       # Clockwise spin in place
RADIUS_SPIN_CCW     =  1       # Counter-clockwise spin in place

# ─── Serial / UART ────────────────────────────────────────────────────────────
DEFAULT_BAUD_RATE   = 115200   # Roomba 650 default after cold boot
SERIAL_TIMEOUT      = 1.0      # seconds — read/write timeout
WAKEUP_PULSE_MS     = 150      # milliseconds — how long RTS is held LOW
WAKEUP_SETTLE_MS    = 500      # milliseconds — wait after wakeup pulse
STARTUP_DELAY_MS    = 200      # milliseconds — after sending START opcode
MODE_CHANGE_DELAY_MS = 50      # milliseconds — after mode-change opcodes
COMMAND_DELAY_MS    = 30       # milliseconds — between consecutive commands
MAX_RETRY_ATTEMPTS  = 3        # serial send retries before giving up

# ─── OI modes (returned by sensor packet 35) ─────────────────────────────────
class OIMode(IntEnum):
    OFF     = 0
    PASSIVE = 1
    SAFE    = 2
    FULL    = 3

# ─── Vision / HuskyLens ──────────────────────────────────────────────────────
# Camera-based vision (OpenCV HOG, Haar cascades, MobileNet SSD) has been
# replaced by the HuskyLens 2 AI vision sensor.
# Old camera constants are preserved in future_features/vision/ for reference.
FOLLOW_DISTANCE_THRESHOLD   = 0.35    # fraction of frame width — stop if target fills this much

# ─── Behavior timing ─────────────────────────────────────────────────────────
SEARCH_TIMEOUT_SEC          = 30      # give up searching for person after N seconds
SEARCH_SPIN_DURATION_SEC    = 2.0     # how long each search spin segment lasts
ROAM_MIN_FORWARD_SEC        = 1.5     # free-roam: min time driving forward
ROAM_MAX_FORWARD_SEC        = 4.0     # free-roam: max time driving forward
ROAM_TURN_DURATION_SEC      = 1.0     # free-roam: how long to turn at a waypoint
OBSTACLE_BACKUP_SEC         = 0.5     # how long to reverse when obstacle hit
OBSTACLE_TURN_SEC           = 0.8     # how long to turn away from obstacle

# ─── AI / Ollama ─────────────────────────────────────────────────────────────
OLLAMA_HOST             = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL    = "llama3.2:1b"       # swap via config — see default_config.yaml
OLLAMA_TIMEOUT_SEC      = 20.0                 # larger models need more time on CPU
AI_MAX_RESPONSE_WORDS   = 12       # hard cap — keep it short
AI_COOLDOWN_SEC         = 8.0      # minimum silence between any speech events

# ─── Audio ───────────────────────────────────────────────────────────────────
TTS_RATE_WPM        = 165      # words per minute for pyttsx3
TTS_VOLUME          = 0.9      # 0.0 – 1.0
SPEECH_QUEUE_MAXLEN = 3        # discard oldest if queue gets this long
WAKE_WORD           = "hey r-seven"   # default wake word phrase

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_DIR             = "logs"
LOG_MAX_BYTES       = 5 * 1024 * 1024   # 5 MB per log file
LOG_BACKUP_COUNT    = 3                 # keep 3 rotated log files
LOG_LEVEL_DEFAULT   = "INFO"
