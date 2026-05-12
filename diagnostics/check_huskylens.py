"""
diagnostics/check_huskylens.py
────────────────────────────────
HuskyLens 2 connectivity and detection test.

Tests:
  1. Serial port is available
  2. Knock / handshake responds OK
  3. Algorithm switch succeeds
  4. Live detection loop — shows what the sensor sees in real time

Usage
─────
    python diagnostics/check_huskylens.py
    python diagnostics/check_huskylens.py --port /dev/ttyUSB1
    python diagnostics/check_huskylens.py --baud 115200
    python diagnostics/check_huskylens.py --algo object_tracking
"""

import sys
import os
import time
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utilities.helpers import find_serial_ports, format_check_result

_C = {
    "green":  "\033[32m", "red":    "\033[31m", "yellow": "\033[33m",
    "cyan":   "\033[36m", "bold":   "\033[1m",  "dim":    "\033[2m",
    "reset":  "\033[0m",
}
def _c(t, c):  return f"{_C.get(c,'')}{t}{_C['reset']}"
def _ok(m):    print(format_check_result(m, True))
def _fail(m):  print(format_check_result(m, False))
def _info(m):  print(_c(f"  ▸  {m}", "cyan"))
def _warn(m):  print(_c(f"  !  {m}", "yellow"))


def main(port: str | None, baud: int, algo: str, duration: int) -> None:
    print()
    print(_c("  R-7 — HuskyLens 2 Diagnostic", "bold"))
    print(_c("  ──────────────────────────────", "cyan"))
    print()

    # ── 1. Port availability ──────────────────────────────────────────────────
    print("  Serial ports:")
    ports = find_serial_ports()
    print(format_check_result("Serial ports found", bool(ports),
                               ", ".join(ports) if ports else "none"))

    if not port:
        if len(ports) >= 2:
            port = ports[1]   # prefer second port (Roomba likely on first)
        elif ports:
            port = ports[0]
        else:
            _fail("No serial ports found")
            print(_c("\n  Fix: check the USB-UART adapter is plugged in", "yellow"))
            print(_c("       ls /dev/ttyUSB*", "cyan"))
            return

    _info(f"Testing port: {port} @ {baud} baud")

    # ── 2. Open serial ────────────────────────────────────────────────────────
    print("\n  Connection:")
    try:
        import serial as _ser
        ser = _ser.Serial(port, baudrate=baud, timeout=0.5, write_timeout=1.0)
        print(format_check_result("Serial port open", True, port))
    except Exception as e:
        print(format_check_result("Serial port open", False, str(e)[:60]))
        print(_c("\n  Fix: sudo usermod -aG dialout $USER  (then log out)", "yellow"))
        return

    # ── 3. Knock / handshake ──────────────────────────────────────────────────
    print("\n  Handshake:")
    from huskylens.protocol import HuskyProtocol, ALGO_IDS
    proto = HuskyProtocol(ser)
    time.sleep(0.3)

    knocked = False
    for attempt in range(3):
        if proto.knock():
            knocked = True
            break
        time.sleep(0.4)

    print(format_check_result("HuskyLens knock OK", knocked,
                               "responded" if knocked else "no response"))
    if not knocked:
        print(_c("\n  Fix: check wiring (TXD↔RXD crossed), baud rate on device,", "yellow"))
        print(_c("       and that Protocol Type = UART in HuskyLens settings", "yellow"))
        ser.close()
        return

    # ── 4. Algorithm switch ───────────────────────────────────────────────────
    print("\n  Algorithm:")
    algo_id = ALGO_IDS.get(algo)
    if algo_id is None:
        _warn(f"Unknown algorithm '{algo}' — skipping switch")
    else:
        ok = proto.set_algorithm(algo_id)
        print(format_check_result(f"Set algorithm: {algo}", ok,
                                   "OK" if ok else "no response"))
        if not ok:
            _warn("Algorithm switch failed — device may not support this algorithm")

    # ── 5. Live detection loop ────────────────────────────────────────────────
    print(f"\n  Live detection ({duration}s — Ctrl+C to stop early):")
    _info(f"Point the HuskyLens at something to detect...")
    print()

    end_time  = time.time() + duration
    last_seen = 0
    frames    = 0
    detections = 0

    try:
        while time.time() < end_time:
            blocks = proto.get_blocks()
            frames += 1

            if blocks:
                detections += 1
                primary = max(blocks, key=lambda b: b.w * b.h)
                side    = ("left"   if primary.x < 100 else
                           "right"  if primary.x > 220 else "center")
                dist    = ("close"  if primary.w > 160 else
                           "medium" if primary.w > 80  else "far")
                id_str  = f"id={primary.id}" if primary.id else "unlearned"
                status  = (f"  🎯  {_c('TARGET', 'green')}  "
                           f"{algo.replace('_',' '):<20}  "
                           f"{side:<6}  {dist:<6}  "
                           f"x={primary.x:3d} y={primary.y:3d}  "
                           f"w={primary.w:3d} h={primary.h:3d}  "
                           f"{id_str}  [{len(blocks)} obj]")
                last_seen = time.time()
            else:
                elapsed = time.time() - last_seen if last_seen else 0
                if elapsed > 1.0 or not last_seen:
                    status = f"  ○  {_c('nothing detected', 'dim')}"
                else:
                    status = f"  ○  {_c('no target', 'dim')}"

            remaining = max(0, int(end_time - time.time()))
            print(f"\r{status}  [{remaining}s]   ", end="", flush=True)
            time.sleep(0.1)

    except KeyboardInterrupt:
        pass

    print(f"\n\n  Frames polled : {frames}")
    print(f"  Detections    : {detections}")
    if frames > 0:
        rate = detections / frames * 100
        print(f"  Detection rate: {rate:.0f}%")

    ser.close()
    print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(_c("  ── Summary ──", "bold"))
    if knocked and detections > 0:
        print(_c("  ✓  HuskyLens working — detections confirmed", "green"))
    elif knocked:
        print(_c("  ✓  HuskyLens connected OK", "green"))
        print(_c("  !  No detections — is the correct algorithm selected on device?", "yellow"))
        _info(f"On HuskyLens home screen, select: {algo.replace('_', ' ').title()}")
    else:
        print(_c("  ✗  HuskyLens handshake failed", "red"))

    print()
    print("  Next steps:")
    print(_c("    python commands/command_console.py   (full system control)", "cyan"))
    print(_c("    python main.py                       (launch droid)", "cyan"))
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HuskyLens 2 connectivity and detection test"
    )
    parser.add_argument("--port",     default=None,              help="Serial port (default: auto)")
    parser.add_argument("--baud",     default=9600,  type=int,   help="Baud rate (default: 9600)")
    parser.add_argument("--algo",     default="face_recognition", help="Algorithm to test")
    parser.add_argument("--duration", default=10,    type=int,   help="Live detection duration in seconds")
    args = parser.parse_args()
    main(args.port, args.baud, args.algo, args.duration)
