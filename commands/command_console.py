"""
commands/command_console.py
────────────────────────────
Full system command console — control ALL subsystems from the terminal.

Unlike roomba/roomba_test.py (which only tests serial/movement),
this console controls the entire live system: vision, AI, audio, behaviours.

Usage
─────
    python commands/command_console.py
    python commands/command_console.py --no-vision    # skip camera startup
    python commands/command_console.py --no-ai        # skip AI/Ollama
    python commands/command_console.py --debug        # verbose logging

Available commands
──────────────────
  MOVEMENT:   forward  backward  left  right  stop
  ROOMBA:     wake  safe  full  clean  dock  battery  bumpers  mode  beep
  BEHAVIOURS: roam  follow  search  idle
  VISION:     vision-debug  vision-status
  AI:         ask <prompt>  ai-status
  AUDIO:      say <text>  mute  unmute
  SYSTEM:     status  config  logs  help  quit
"""

import sys
import os
import argparse
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from roomba.controller      import RoombaController
from vision.vision_manager  import VisionManager
from ai.personality         import Personality
from ai.ollama_client       import OllamaClient
from audio.tts_manager      import TTSManager
from behaviors.behavior_manager import BehaviorManager, BehaviorState
from utilities.logger       import get_logger, set_global_level
from utilities.helpers      import find_serial_ports
from config.config_loader   import get_config, dump_config

log = get_logger(__name__)

# ─── Colour helpers ──────────────────────────────────────────────────────────
def _c(text, colour):
    codes = {"green":"\033[32m","red":"\033[31m","yellow":"\033[33m",
             "cyan":"\033[36m","bold":"\033[1m","reset":"\033[0m","dim":"\033[2m"}
    return f"{codes.get(colour,'')}{text}{codes['reset']}"

def _ok(m):   print(_c(f"  ✓  {m}", "green"))
def _fail(m): print(_c(f"  ✗  {m}", "red"))
def _info(m): print(_c(f"  ▸  {m}", "cyan"))
def _warn(m): print(_c(f"  !  {m}", "yellow"))
def _section(m): print("\n" + _c(f"  ── {m} ──", "bold"))


HELP_TEXT = """
┌─────────────────────────────────────────────────────────────────────┐
│                   R-7 Droid — Command Console                       │
├─────────────────┬───────────────────────────────────────────────────┤
│ MOVEMENT        │ forward [sec]  backward [sec]  left [deg]         │
│                 │ right [deg]    stop                               │
├─────────────────┼───────────────────────────────────────────────────┤
│ ROOMBA          │ wake  safe  full  beep  clean  dock               │
│                 │ battery  bumpers  mode                            │
├─────────────────┼───────────────────────────────────────────────────┤
│ BEHAVIOURS      │ roam  follow  search  idle                        │
├─────────────────┼───────────────────────────────────────────────────┤
│ VISION          │ vision-debug  vision-status                       │
├─────────────────┼───────────────────────────────────────────────────┤
│ AI / SPEECH     │ ask <question>   say <text>   ai-status           │
│                 │ mute    unmute                                    │
├─────────────────┼───────────────────────────────────────────────────┤
│ SYSTEM          │ status  config  help  quit                        │
└─────────────────┴───────────────────────────────────────────────────┘
"""


class DroidConsole:
    """Full system interactive console."""

    def __init__(self, args):
        self._args       = args
        self._roomba     = RoombaController()
        self._vision:    VisionManager  | None = None
        self._tts        = TTSManager()
        self._personality = Personality()
        self._ai         = OllamaClient()
        self._behavior:  BehaviorManager | None = None
        self._muted      = False

    def start(self) -> bool:
        """Initialise all subsystems."""
        _section("Starting R-7 Droid System")
        cfg = get_config()

        # ── Roomba ──────────────────────────────────────────────────
        _info("Connecting to Roomba...")
        if not self._roomba.startup():
            _fail("Could not connect to Roomba — check serial port and wiring")
            _warn("Run 'python roomba/roomba_test.py' to diagnose serial issues")
            return False
        _ok("Roomba connected")

        # ── TTS ─────────────────────────────────────────────────────
        if cfg["audio"].get("tts_enabled", True):
            _info("Starting TTS engine...")
            if self._tts.start():
                _ok("TTS ready")
            else:
                _warn("TTS failed to start — speech disabled")

        # ── Vision ──────────────────────────────────────────────────
        if not self._args.no_vision:
            _info("Starting vision system...")
            self._vision = VisionManager()
            if self._vision.start():
                _ok("Vision system running")
            else:
                _warn("Vision failed to start — running without camera")
                self._vision = None

        # ── AI ──────────────────────────────────────────────────────
        if not self._args.no_ai:
            _info("Checking AI (Ollama)...")
            if self._ai.is_available():
                _ok(f"Ollama available (model: {cfg['ai']['model']})")
            else:
                _warn("Ollama not available — personality phrases only")

        # ── Behaviours ──────────────────────────────────────────────
        if self._vision:
            self._behavior = BehaviorManager(
                roomba     = self._roomba,
                vision     = self._vision,
                tts        = self._tts,
                personality = self._personality,
                ai_client  = self._ai if not self._args.no_ai else None,
            )

        # ── Greet ───────────────────────────────────────────────────
        greeting = self._personality.greeting()
        _ok(f"System ready — {greeting}")
        if not self._muted:
            self._tts.speak(greeting)

        return True

    def stop(self) -> None:
        """Clean shutdown of all subsystems."""
        _section("Shutting down...")
        if self._behavior:
            self._behavior.stop()
        if self._vision:
            self._vision.stop()
        self._tts.stop()
        self._roomba.shutdown()
        _ok("All systems shut down. Goodbye!")

    def run(self) -> None:
        """Main interactive loop."""
        print()
        print(_c("  R-7 Droid — Command Console", "bold"))
        print(_c("  Type 'help' for commands", "dim"))
        print()

        while True:
            try:
                # Status colour in prompt
                roomba_state = self._roomba.state.name
                bstate = self._behavior.state.name if self._behavior else "NO_VISION"
                prompt = (
                    _c(f"[{roomba_state}]", "cyan") +
                    _c(f"[{bstate}]", "green") +
                    " > "
                )

                raw   = input(prompt).strip()
                if not raw:
                    continue
                parts = raw.split(None, 2)   # split into max 3 parts
                cmd   = parts[0].lower()
                args  = parts[1:]

                self._dispatch(cmd, args)

            except KeyboardInterrupt:
                print()
                _info("Ctrl+C — shutting down...")
                self.stop()
                break
            except EOFError:
                self.stop()
                break

    def _dispatch(self, cmd: str, args: list[str]) -> None:
        """Route a command to the right handler."""
        r = self._roomba

        # ── Movement ────────────────────────────────────────────────
        if cmd == "forward":
            dur = float(args[0]) if args else 1.0
            r.forward(dur); _ok(f"Forward {dur}s")

        elif cmd == "backward":
            dur = float(args[0]) if args else 1.0
            r.backward(dur); _ok(f"Backward {dur}s")

        elif cmd == "left":
            deg = float(args[0]) if args else 90.0
            r.spin_left(deg); _ok(f"Left ~{deg}°")

        elif cmd == "right":
            deg = float(args[0]) if args else 90.0
            r.spin_right(deg); _ok(f"Right ~{deg}°")

        elif cmd == "stop":
            r.stop(); _ok("Stopped")

        # ── Roomba ──────────────────────────────────────────────────
        elif cmd == "wake":
            r._serial.wakeup(); _ok("Wakeup pulse sent")

        elif cmd == "safe":
            r.set_safe_mode(); _ok("Safe mode")

        elif cmd == "full":
            _warn("Full mode — safety stops DISABLED")
            if input("    Confirm (yes): ").strip().lower() == "yes":
                r.set_full_mode()

        elif cmd == "beep":
            r.beep(); _ok("Beep!")

        elif cmd == "clean":
            r.clean(); _ok("Clean cycle started")

        elif cmd == "dock":
            r.dock(); _ok("Docking...")

        elif cmd == "battery":
            data = r.read_battery()
            if data:
                _ok(f"Battery: {data['pct']:.1f}%  |  {data['voltage_mv']} mV")

        elif cmd == "bumpers":
            data = r.read_bumpers()
            if data:
                _ok(f"Left: {'HIT' if data['left'] else 'clear'}  "
                    f"Right: {'HIT' if data['right'] else 'clear'}")

        elif cmd == "mode":
            m = r.read_oi_mode()
            names = {0:"OFF",1:"PASSIVE",2:"SAFE",3:"FULL"}
            _ok(f"OI mode: {names.get(m,'?')} ({m})")

        # ── Behaviours ──────────────────────────────────────────────
        elif cmd == "roam":
            if self._behavior:
                self._behavior.force_state(BehaviorState.FREE_ROAM)
                if not self._behavior._thread or not self._behavior._thread.is_alive():
                    self._behavior.start()
                _ok("Free roam mode")

        elif cmd == "follow":
            if self._behavior:
                self._behavior.force_state(BehaviorState.FOLLOW_PERSON)
                _ok("Follow person mode")
            else:
                _fail("Vision not available — cannot follow")

        elif cmd == "search":
            if self._behavior:
                self._behavior.force_state(BehaviorState.SEARCH_PERSON)
                _ok("Search mode")

        elif cmd == "idle":
            if self._behavior:
                self._behavior.stop()
            r.stop()
            _ok("Idle — all behaviours stopped")

        # ── Vision ──────────────────────────────────────────────────
        elif cmd == "vision-debug":
            if self._vision:
                self._vision.enable_debug_display(True)
                _ok("Vision debug window opened (press q to close)")
            else:
                _fail("Vision not running")

        elif cmd == "vision-status":
            if self._vision:
                vs = self._vision.get_vision_state()
                _ok(f"Vision: person={vs.person_detected}  "
                    f"face={vs.face_detected}  "
                    f"offset={vs.target_x_offset:.2f}  "
                    f"fill={vs.target_fill:.2f}  "
                    f"frames={vs.frame_count}")
            else:
                _fail("Vision not running")

        # ── AI / Speech ──────────────────────────────────────────────
        elif cmd == "ask":
            prompt = " ".join(args) if args else "What should I do?"
            _info(f"Asking AI: {prompt}")
            response = self._ai.ask(prompt)
            if response:
                filtered = self._personality.filter_ai_response(response)
                _ok(f"AI says: {filtered}")
                if not self._muted:
                    self._tts.speak(filtered)
            else:
                _fail("AI unavailable")

        elif cmd == "say":
            text = " ".join(args) if args else ""
            if text and not self._muted:
                self._tts.speak(text, priority=True)
                _ok(f"Speaking: {text}")

        elif cmd == "mute":
            self._muted = True; _ok("Muted")

        elif cmd == "unmute":
            self._muted = False; _ok("Unmuted")

        elif cmd == "ai-status":
            info = self._ai.get_model_info()
            _ok(f"AI: model={info['model']}  "
                f"available={info['available']}  "
                f"host={info['host']}")

        # ── System ───────────────────────────────────────────────────
        elif cmd == "status":
            self._print_status()

        elif cmd == "config":
            print(dump_config())

        elif cmd in ("help", "?"):
            print(HELP_TEXT)

        elif cmd in ("quit", "exit", "q"):
            self.stop()
            sys.exit(0)

        else:
            _warn(f"Unknown command: '{cmd}' — type 'help'")

    def _print_status(self) -> None:
        status = self._roomba.get_status()
        _section("System Status")
        print(f"    Roomba    : {_c(status['state'], 'cyan')}")
        print(f"    Battery   : {status['battery_pct']:.1f}%")
        if self._behavior:
            print(f"    Behaviour : {_c(self._behavior.state.name, 'green')}")
        if self._vision:
            vs = self._vision.get_vision_state()
            print(f"    Vision    : person={vs.person_detected}  frames={vs.frame_count}")
        print(f"    AI        : {'available' if self._ai.is_available() else _c('offline', 'yellow')}")
        print(f"    TTS       : {'speaking' if self._tts.is_speaking else 'idle'}  "
              f"muted={'yes' if self._muted else 'no'}")
        print()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="R-7 Droid command console")
    parser.add_argument("--no-vision", action="store_true", help="Disable vision system")
    parser.add_argument("--no-ai",     action="store_true", help="Disable AI/Ollama")
    parser.add_argument("--debug",     action="store_true", help="Enable debug logging")
    parser.add_argument("--port",      default=None, help="Serial port override")
    args = parser.parse_args()

    if args.debug:
        set_global_level("DEBUG")

    console = DroidConsole(args)
    if console.start():
        console.run()
    else:
        print(_c("\n  System startup failed. See logs/ for details.\n", "red"))
        sys.exit(1)
