"""
utilities/logger.py
───────────────────
Centralised logging factory for the entire project.

Every module should import `get_logger(__name__)` rather than calling
logging.getLogger() directly.  This guarantees:

  • Consistent log format across all subsystems
  • Colour-coded console output (DEBUG=cyan, INFO=green, WARN=yellow, ERROR=red)
  • Automatic log rotation to the logs/ directory
  • A single place to change verbosity for the whole project

Usage
─────
    from utilities.logger import get_logger
    log = get_logger(__name__)
    log.info("Connected to Roomba")
    log.warning("Sensor packet timeout")
    log.error("Serial port not found")
    log.debug("Sent opcode 131 (SAFE)")
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from utilities.constants import LOG_DIR, LOG_MAX_BYTES, LOG_BACKUP_COUNT, LOG_LEVEL_DEFAULT

# ─── ANSI colour codes for terminal output ───────────────────────────────────
# These only apply to the StreamHandler (console).  File logs are plain text.
_RESET  = "\033[0m"
_COLOURS = {
    logging.DEBUG:    "\033[36m",   # Cyan
    logging.INFO:     "\033[32m",   # Green
    logging.WARNING:  "\033[33m",   # Yellow
    logging.ERROR:    "\033[31m",   # Red
    logging.CRITICAL: "\033[35m",   # Magenta
}

# ─── Tag aliases that appear in the log prefix ───────────────────────────────
# We derive a short tag from the module name so logs read like:
#   [ROOMBA] Connected on /dev/ttyUSB0
#   [VISION] Person detected
_TAG_MAP = {
    "roomba":     "ROOMBA",
    "vision":     "VISION",
    "ai":         "AI",
    "audio":      "AUDIO",
    "behaviors":  "BEHAVIOR",
    "commands":   "CMD",
    "utilities":  "UTIL",
    "diagnostics":"DIAG",
    "__main__":   "MAIN",
}


def _make_tag(name: str) -> str:
    """Convert a dotted module name like 'roomba.controller' → 'ROOMBA'."""
    root = name.split(".")[0]
    return _TAG_MAP.get(root, root.upper()[:8])


class _ColouredFormatter(logging.Formatter):
    """
    Custom formatter that adds colour to console output and converts the
    dotted logger name into a short, readable tag.
    """
    def format(self, record: logging.LogRecord) -> str:
        tag   = _make_tag(record.name)
        colour = _COLOURS.get(record.levelno, _RESET)
        time   = self.formatTime(record, "%H:%M:%S")
        level  = record.levelname[0]          # single letter: D I W E C
        msg    = record.getMessage()

        # Show exception info if present
        exc = ""
        if record.exc_info:
            exc = "\n" + self.formatException(record.exc_info)

        return f"{colour}[{tag}] {time} {level}  {msg}{exc}{_RESET}"


class _PlainFormatter(logging.Formatter):
    """Plain formatter for file-based log rotation — no ANSI codes."""
    def format(self, record: logging.LogRecord) -> str:
        tag  = _make_tag(record.name)
        time = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        msg  = record.getMessage()
        exc  = ""
        if record.exc_info:
            exc = "\n" + self.formatException(record.exc_info)
        return f"[{tag}] {time} {record.levelname:<8} {msg}{exc}"


# ─── Module-level cache so we don't add duplicate handlers ───────────────────
_initialised = False


def _setup_root_logger(level: str = LOG_LEVEL_DEFAULT) -> None:
    """
    Configure the root logger ONCE.
    Called lazily on first get_logger() call.
    """
    global _initialised
    if _initialised:
        return
    _initialised = True

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)   # root captures everything; handlers filter

    # ── Console handler (coloured) ──────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    console_handler.setFormatter(_ColouredFormatter())
    root.addHandler(console_handler)

    # ── Rotating file handler ───────────────────────────────────────────────
    log_path = Path(LOG_DIR)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "droid.log"

    file_handler = logging.handlers.RotatingFileHandler(
        filename    = str(log_file),
        maxBytes    = LOG_MAX_BYTES,
        backupCount = LOG_BACKUP_COUNT,
        encoding    = "utf-8",
    )
    file_handler.setLevel(logging.DEBUG)   # always verbose in the file
    file_handler.setFormatter(_PlainFormatter())
    root.addHandler(file_handler)

    # Suppress noisy third-party libraries unless we're at DEBUG level
    if level.upper() != "DEBUG":
        for noisy in ("urllib3", "httpx", "httpcore", "PIL", "cv2"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str, level: str | None = None) -> logging.Logger:
    """
    Return a logger for `name`.

    Parameters
    ----------
    name  : typically __name__ of the calling module
    level : override console level for this specific logger (e.g. "DEBUG")

    Example
    -------
        log = get_logger(__name__)
        log.info("Hello")
    """
    _setup_root_logger()
    logger = logging.getLogger(name)
    if level:
        logger.setLevel(getattr(logging, level.upper(), logging.DEBUG))
    return logger


def set_global_level(level: str) -> None:
    """
    Change the console log level at runtime.
    Useful for a `--debug` CLI flag.

    Example
    -------
        set_global_level("DEBUG")
    """
    lvl = getattr(logging, level.upper(), logging.INFO)
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.handlers.RotatingFileHandler
        ):
            handler.setLevel(lvl)
