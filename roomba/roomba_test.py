"""
roomba/roomba_test.py
──────────────────────
Interactive command-line test interface for the Roomba.

PURPOSE: Test Roomba serial communication in complete isolation from
the rest of the project.  If something doesn't work, start here.

Usage
─────
    python roomba/roomba_test.py
    python roomba/roomba_test.py --port /dev/ttyUSB0
    python roomba/roomba_test.py --debug

Available commands at the prompt
──────────────────────────────────
  connect     — open serial port and run startup sequence
  disconnect  — close serial port
  status      — show current state
  wake        — send RTS wakeup pulse only
  safe        — enter Safe mode
  full        — enter Full mode (careful!)
  forward     — drive forward 1 second
  backward    — drive backward 1 second
  left        — spin left 90°
  right       — spin right 90°
  stop        — stop immediately
  beep        — play droid beep
  clean       — start clean cycle
  dock        — seek charging dock
  battery     — read battery state
  bumpers     — read bump sensors
  mode        — read OI mode from Roomba
  reset       — soft-reset the OI
  ports       — list available serial ports
  help        — show this list
  quit / exit — exit the test console
"""

import sys
import os
import argparse

# ─── Make sure project root is on path ───────────────────────────────────────
# This allows running the script directly as: python roomba/roomba_test.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from roomba.controller import RoombaController, ControllerState
from roomba.serial_manager import SerialManager
from utilities.logger import get_logger, set_global_level
from utilities.helpers import find_serial_ports

log = get_logger(__name__)


# ─── Colour helpers ──────────────────────────────────────────────────────────
def _c(text: str, colour: str) -> str:
    codes = {"green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m",
             "cyan": "\033[36m", "bold": "\033[1m", "reset": "\033[0m"}
    return f"{codes.get(colour,'')}{text}{codes['reset']}"


def _ok(msg):   print(_c(f"  ✓  {msg}", "green"))
def _fail(msg): print(_c(f"  ✗  {msg}", "red"))
def _info(msg): print(_c(f"  ▸  {msg}", "cyan"))
def _warn(msg): print(_c(f"  !  {msg}", "yellow"))


# ─── Command handlers ─────────────────────────────────────────────────────────

def cmd_connect(roomba: RoombaController, port: str | None) -> None:
    _info("Running startup sequence...")
    if roomba.startup(port):
        _ok(f"Connected and in {roomba.state.name} mode")
    else:
        _fail("Startup failed — check serial port and wiring")


def cmd_status(roomba: RoombaController) -> None:
    status = roomba.get_status()
    print()
    print(_c("  Current Status", "bold"))
    print(f"    State     : {_c(status['state'], 'cyan')}")
    print(f"    Connected : {'yes' if status['connected'] else _c('no', 'red')}")
    print(f"    Battery   : {status['battery_pct']:.1f}%  ({status['voltage_mv']} mV)")
    print(f"    Bump L/R  : {status['bump_left']} / {status['bump_right']}")
    print()


def cmd_ports() -> None:
    ports = find_serial_ports()
    if ports:
        _info(f"Available serial ports ({len(ports)}):")
        for p in ports:
            print(f"    {p}")
    else:
        _warn("No serial ports found. Is the USB adapter plugged in?")
        print("    Try: ls /dev/ttyUSB*  or  ls /dev/ttyACM*")


HELP_TEXT = """
  ┌─────────────────────────────────────────────────────────┐
  │              R-7 Roomba Test Console                    │
  ├──────────────────┬──────────────────────────────────────┤
  │  CONNECTION      │  connect    disconnect   ports        │
  │  MODE            │  wake       safe         full        │
  │  MOVEMENT        │  forward    backward     stop        │
  │                  │  left       right                    │
  │  ACTIONS         │  beep       clean        dock        │
  │  SENSORS         │  battery    bumpers      mode        │
  │  SYSTEM          │  status     reset        help  quit  │
  └──────────────────┴──────────────────────────────────────┘
"""


def run_console(port: str | None = None) -> None:
    """Main interactive loop."""
    roomba = RoombaController()

    print()
    print(_c("  R-7 Droid — Roomba Test Console", "bold"))
    print(_c("  ─────────────────────────────────────", "cyan"))
    print("  Type 'help' for commands, 'connect' to start, 'quit' to exit.")
    print()

    # Auto-detect port info
    available = find_serial_ports()
    if available:
        _info(f"Serial ports found: {', '.join(available)}")
    else:
        _warn("No serial ports detected — check USB adapter")
    print()

    while True:
        try:
            # Show a coloured state indicator in the prompt
            state_label = roomba.state.name if roomba.is_connected else "OFFLINE"
            colour = "green" if roomba.is_active else ("cyan" if roomba.is_connected else "red")
            prompt = _c(f"[{state_label}]", colour) + " > "

            raw = input(prompt).strip().lower()
            if not raw:
                continue

            # Split command and optional args
            parts = raw.split()
            cmd   = parts[0]
            args  = parts[1:]

            # ── Connection ──────────────────────────────────────────
            if cmd == "connect":
                p = args[0] if args else port
                cmd_connect(roomba, p)

            elif cmd == "disconnect":
                roomba.shutdown()
                _ok("Disconnected")

            elif cmd == "ports":
                cmd_ports()

            # ── Mode ────────────────────────────────────────────────
            elif cmd == "wake":
                if roomba.is_connected:
                    roomba._serial.wakeup()
                    _ok("Wakeup pulse sent")
                else:
                    _fail("Not connected — run 'connect' first")

            elif cmd == "safe":
                if roomba.set_safe_mode():
                    _ok("Entered Safe mode")
                else:
                    _fail("Failed to enter Safe mode")

            elif cmd == "full":
                _warn("Full mode disables all safety stops!")
                confirm = input("  Type 'yes' to confirm: ").strip().lower()
                if confirm == "yes":
                    if roomba.set_full_mode():
                        _ok("Entered Full mode")
                    else:
                        _fail("Failed to enter Full mode")
                else:
                    _info("Cancelled")

            elif cmd == "reset":
                from roomba.opcodes import cmd_reset
                roomba._serial.send(cmd_reset(), "RESET")
                _ok("Reset command sent — Roomba will restart OI")

            # ── Movement ────────────────────────────────────────────
            elif cmd == "forward":
                dur = float(args[0]) if args else 1.0
                _info(f"Driving forward for {dur}s...")
                roomba.forward(dur)
                _ok("Done")

            elif cmd == "backward":
                dur = float(args[0]) if args else 1.0
                _info(f"Driving backward for {dur}s...")
                roomba.backward(dur)
                _ok("Done")

            elif cmd == "left":
                deg = float(args[0]) if args else 90.0
                _info(f"Spinning left ~{deg}°...")
                roomba.spin_left(deg)
                _ok("Done")

            elif cmd == "right":
                deg = float(args[0]) if args else 90.0
                _info(f"Spinning right ~{deg}°...")
                roomba.spin_right(deg)
                _ok("Done")

            elif cmd == "stop":
                roomba.stop()
                _ok("Stopped")

            # ── Actions ──────────────────────────────────────────────
            elif cmd == "beep":
                roomba.beep()
                _ok("Beep!")

            elif cmd == "clean":
                _warn("Starting clean cycle — Roomba takes control")
                roomba.clean()
                _ok("Clean command sent")

            elif cmd == "dock":
                _info("Seeking dock...")
                roomba.dock()
                _ok("Dock command sent — Roomba navigating to dock")

            # ── Sensors ──────────────────────────────────────────────
            elif cmd == "battery":
                data = roomba.read_battery()
                if data:
                    _ok(f"Battery: {data['pct']:.1f}%  |  {data['voltage_mv']} mV  |  "
                        f"{data['charge_mah']}/{data['capacity_mah']} mAh")
                else:
                    _fail("Could not read battery (not connected or mode issue)")

            elif cmd == "bumpers":
                data = roomba.read_bumpers()
                if data:
                    l = "PRESSED" if data["left"]  else "clear"
                    r = "PRESSED" if data["right"] else "clear"
                    _ok(f"Left bumper: {l}   Right bumper: {r}")
                else:
                    _fail("Could not read bump sensors")

            elif cmd == "mode":
                mode = roomba.read_oi_mode()
                if mode is not None:
                    names = {0: "OFF", 1: "PASSIVE", 2: "SAFE", 3: "FULL"}
                    _ok(f"OI mode reported by Roomba: {names.get(mode, '?')} ({mode})")
                else:
                    _fail("No response to mode query")

            # ── System ───────────────────────────────────────────────
            elif cmd == "status":
                cmd_status(roomba)

            elif cmd in ("help", "?"):
                print(HELP_TEXT)

            elif cmd in ("quit", "exit", "q"):
                _info("Shutting down...")
                roomba.shutdown()
                print(_c("  Goodbye!", "cyan"))
                break

            else:
                _warn(f"Unknown command: '{cmd}'  — type 'help' for options")

        except KeyboardInterrupt:
            print()
            _info("Ctrl+C — shutting down...")
            roomba.shutdown()
            break
        except EOFError:
            roomba.shutdown()
            break
        except Exception as e:
            _fail(f"Unexpected error: {e}")
            log.exception("Unexpected error in test console")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="R-7 Droid — Interactive Roomba test console",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example: python roomba/roomba_test.py --port /dev/ttyUSB0 --debug"
    )
    parser.add_argument("--port",  default=None, help="Serial port (default: auto-detect)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args()

    if args.debug:
        set_global_level("DEBUG")

    run_console(port=args.port)
