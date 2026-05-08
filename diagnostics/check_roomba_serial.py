"""
diagnostics/check_roomba_serial.py
────────────────────────────────────
Deep diagnostic for Roomba serial communication.

Tests performed
───────────────
  1. List all serial ports on the system
  2. Attempt to open the target port
  3. Send RTS wakeup pulse
  4. Send START opcode
  5. Enter Safe mode
  6. Query OI mode sensor — verify Roomba responds
  7. Send a beep command
  8. Read battery data
  9. Stop and disconnect

Run this script FIRST when debugging Roomba issues.
It will tell you exactly where in the chain things are failing.

Usage
─────
    python diagnostics/check_roomba_serial.py
    python diagnostics/check_roomba_serial.py --port /dev/ttyUSB0
    python diagnostics/check_roomba_serial.py --port /dev/ttyUSB0 --move
"""

import sys
import os
import time
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utilities.helpers import find_serial_ports, format_check_result, sleep_ms, bytes_to_hex
from utilities.constants import OI, Sensor

# ─── Terminal colours ─────────────────────────────────────────────────────────
def _c(t, c):
    codes={"green":"\033[32m","red":"\033[31m","yellow":"\033[33m",
           "cyan":"\033[36m","bold":"\033[1m","reset":"\033[0m"}
    return f"{codes.get(c,'')}{t}{codes['reset']}"

def _head(t): print("\n" + _c(f"  ── {t} ──", "bold"))
def _ok(m):   print(_c(f"    ✓  {m}", "green"))
def _fail(m): print(_c(f"    ✗  {m}", "red"))
def _info(m): print(_c(f"    ▸  {m}", "cyan"))
def _warn(m): print(_c(f"    !  {m}", "yellow"))


def run_diagnostics(port: str | None, run_move_test: bool = False) -> bool:
    """
    Run the full serial diagnostic suite.
    Returns True if all critical tests passed.
    """
    print()
    print(_c("  R-7 Droid — Roomba Serial Diagnostics", "bold"))
    print(_c("  ───────────────────────────────────────", "cyan"))

    all_passed = True

    # ── TEST 1: pyserial import ───────────────────────────────────────────────
    _head("Test 1: Python dependencies")
    try:
        import serial
        import serial.tools.list_ports
        _ok(f"pyserial version: {serial.VERSION}")
    except ImportError:
        _fail("pyserial NOT installed")
        _info("Fix:  pip install pyserial")
        return False

    # ── TEST 2: list available ports ──────────────────────────────────────────
    _head("Test 2: Available serial ports")
    ports = find_serial_ports()
    if ports:
        for p in ports:
            _ok(f"Found: {p}")
    else:
        _fail("No serial ports detected")
        _warn("Check that your USB-UART adapter is plugged in")
        _info("On Linux, check: ls /dev/ttyUSB*  and  ls /dev/ttyACM*")
        _info("You may need to add yourself to the dialout group:")
        _info("  sudo usermod -aG dialout $USER   (then log out + back in)")
        all_passed = False

    # ── TEST 3: determine target port ─────────────────────────────────────────
    _head("Test 3: Target port selection")
    from utilities.helpers import best_guess_roomba_port

    target = port or best_guess_roomba_port()
    if target:
        _ok(f"Target port: {target}")
    else:
        _fail("No port specified and auto-detection found nothing")
        _info("Use: python diagnostics/check_roomba_serial.py --port /dev/ttyUSB0")
        return False

    # ── TEST 4: open port ─────────────────────────────────────────────────────
    _head("Test 4: Open serial port")
    try:
        s = serial.Serial(
            port     = target,
            baudrate = 115200,
            bytesize = serial.EIGHTBITS,
            parity   = serial.PARITY_NONE,
            stopbits = serial.STOPBITS_ONE,
            timeout  = 1.0,
            rtscts   = False,
            dsrdtr   = False,
        )
        _ok(f"Port {target} opened at 115200 baud")
    except serial.SerialException as e:
        _fail(f"Cannot open {target}: {e}")
        _warn("Possible causes:")
        _info("  • Port is in use by another program")
        _info("  • Wrong permissions — check: ls -l /dev/ttyUSB*")
        _info("  • Adapter not detected — try unplugging and re-plugging")
        return False

    # ── TEST 5: RTS wakeup ────────────────────────────────────────────────────
    _head("Test 5: RTS wakeup pulse")
    _info("Sending RTS LOW pulse (150 ms)...")
    _info("The Roomba should play a startup beep if it was asleep")
    try:
        s.setRTS(True)   # LOW
        time.sleep(0.150)
        s.setRTS(False)  # HIGH
        time.sleep(0.500)  # wait for Roomba to wake up
        _ok("RTS pulse sent — waiting 500 ms for Roomba to settle")
    except Exception as e:
        _fail(f"RTS control failed: {e}")
        _warn("Some cheap UART adapters don't support RTS control")
        _info("Try a different adapter (CP2102, FTDI232 recommended)")
        all_passed = False

    # ── TEST 6: send START opcode ─────────────────────────────────────────────
    _head("Test 6: Send START opcode (128)")
    try:
        s.reset_input_buffer()
        s.write(bytes([OI.START]))
        s.flush()
        time.sleep(0.200)
        _ok(f"START opcode sent: {bytes_to_hex(bytes([OI.START]))}")
    except Exception as e:
        _fail(f"Write failed: {e}")
        s.close()
        return False

    # ── TEST 7: enter Safe mode ───────────────────────────────────────────────
    _head("Test 7: Enter Safe mode (131)")
    try:
        s.write(bytes([OI.SAFE]))
        s.flush()
        time.sleep(0.050)
        _ok(f"SAFE opcode sent: {bytes_to_hex(bytes([OI.SAFE]))}")
    except Exception as e:
        _fail(f"SAFE write failed: {e}")
        all_passed = False

    # ── TEST 8: query OI mode ─────────────────────────────────────────────────
    _head("Test 8: Query OI mode sensor (verify Roomba responds)")
    try:
        s.reset_input_buffer()
        s.write(bytes([OI.SENSORS, Sensor.OI_MODE]))
        s.flush()
        time.sleep(0.050)
        data = s.read(1)
        if data:
            mode = data[0]
            names = {0:"OFF", 1:"PASSIVE", 2:"SAFE", 3:"FULL"}
            _ok(f"Roomba responded!  OI mode = {names.get(mode,'?')} ({mode})")
            if mode == 2:
                _ok("Confirmed: Roomba is in SAFE mode")
            else:
                _warn(f"Unexpected mode {mode} — expected 2 (SAFE)")
        else:
            _fail("No response from Roomba to sensor query")
            _warn("Possible causes:")
            _info("  • TX/RX wires swapped (try swapping RXD and TXD)")
            _info("  • Roomba not fully awake — try holding the Clean button first")
            _info("  • Baud rate mismatch (try 19200 if 115200 doesn't work)")
            all_passed = False
    except Exception as e:
        _fail(f"Sensor query failed: {e}")
        all_passed = False

    # ── TEST 9: send beep ─────────────────────────────────────────────────────
    _head("Test 9: Send beep (song define + play)")
    _info("You should hear the Roomba's built-in speaker beep...")
    try:
        # Define song 0: middle C for 0.5 sec, then G for 0.25 sec
        song = bytes([OI.SONG, 0, 2, 60, 32, 67, 16])
        play = bytes([OI.PLAY, 0])
        s.write(song + play)
        s.flush()
        time.sleep(1.5)   # wait for song to finish
        _ok("Beep command sent — did you hear the Roomba?")
    except Exception as e:
        _fail(f"Beep failed: {e}")

    # ── TEST 10: read battery ─────────────────────────────────────────────────
    _head("Test 10: Read battery state")
    try:
        from utilities.helpers import unpack_unsigned_16
        s.reset_input_buffer()
        # Query list: voltage (22), battery charge (25), battery capacity (26)
        s.write(bytes([OI.QUERY_LIST, 3, Sensor.VOLTAGE, Sensor.BATTERY_CHARGE, Sensor.BATTERY_CAPACITY]))
        s.flush()
        time.sleep(0.050)
        data = s.read(6)
        if len(data) == 6:
            voltage  = unpack_unsigned_16(data, 0)
            charge   = unpack_unsigned_16(data, 2)
            capacity = unpack_unsigned_16(data, 4)
            pct      = (charge / capacity * 100) if capacity > 0 else 0
            _ok(f"Battery: {pct:.1f}%  |  {voltage} mV  |  {charge}/{capacity} mAh")
        else:
            _warn(f"Battery read returned {len(data)} bytes (expected 6)")
    except Exception as e:
        _warn(f"Battery read failed: {e}")

    # ── TEST 11: optional movement test ───────────────────────────────────────
    if run_move_test:
        _head("Test 11: Movement test (DRIVE_DIRECT)")
        _warn("The Roomba WILL MOVE during this test. Clear the area!")
        confirm = input("    Press Enter to continue, or type 'skip' to skip: ")
        if confirm.strip().lower() != "skip":
            from utilities.helpers import pack_signed_16
            _info("Driving forward at 150 mm/s for 0.5 seconds...")
            # DRIVE_DIRECT: right=150, left=150
            cmd = bytes([OI.DRIVE_DIRECT]) + pack_signed_16(150) + pack_signed_16(150)
            s.write(cmd)
            s.flush()
            time.sleep(0.5)
            # Stop
            s.write(bytes([OI.DRIVE_DIRECT]) + pack_signed_16(0) + pack_signed_16(0))
            s.flush()
            _ok("Movement test complete")
            _info("Did the Roomba move? If not, check SAFE mode and battery")

    # ── CLOSE ─────────────────────────────────────────────────────────────────
    _head("Cleanup")
    try:
        # Send stop and return to passive
        s.write(bytes([OI.DRIVE_DIRECT]) + bytes([0,0,0,0]))
        s.flush()
        time.sleep(0.050)
        s.close()
        _ok("Port closed")
    except Exception:
        pass

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    print()
    print(_c("  ── Diagnostic Summary ──", "bold"))
    if all_passed:
        print(_c("  All critical tests passed.  Roomba communication is working!", "green"))
        print(_c("  Next: run  python roomba/roomba_test.py  for interactive testing.", "cyan"))
    else:
        print(_c("  Some tests FAILED.  Review the errors above.", "red"))
        print("  Common fixes:")
        print("    • Check wiring: Roomba RXD→adapter TXD, TXD→RXD, RTS→RTS, GND→GND")
        print("    • Check permissions: sudo usermod -aG dialout $USER")
        print("    • Try a different USB port")
        print("    • Make sure Roomba battery is charged")
    print()

    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Roomba serial diagnostics")
    parser.add_argument("--port", default=None, help="Serial port to test")
    parser.add_argument("--move", action="store_true", help="Include movement test")
    args = parser.parse_args()
    success = run_diagnostics(args.port, args.move)
    sys.exit(0 if success else 1)
