"""
commands/command_console.py
────────────────────────────
Full system command console.

Live feed shown in terminal
────────────────────────────
  🔊 SPEAKING   "Oh! I found you!"          ← everything the droid says
  🎤 HEARD      "hey r-seven find me"       ← everything the mic picks up
  🤖 AI         model=llama3.2:1b           ← AI status changes

Rules enforced here
────────────────────
  • Personality/canned phrases NEVER fire while AI is generating or speaking.
  • STT input is shown even when it doesn't pass the wake-word filter.
  • TTS output is shown regardless of which subsystem triggered it.

Usage
─────
    python commands/command_console.py
    python commands/command_console.py --no-vision
    python commands/command_console.py --no-ai
    python commands/command_console.py --debug
"""

import sys
import os
import time
import threading
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from roomba.controller              import RoombaController
from huskylens.huskylens_manager    import HuskyLensManager
from huskylens.protocol             import ALGO_IDS
from ai.personality                 import Personality
from ai.ollama_client           import OllamaClient
from audio.tts_manager          import TTSManager
from audio.stt_manager          import STTManager
from behaviors.behavior_manager import BehaviorManager, BehaviorState
from utilities.logger           import get_logger, set_global_level
from utilities.helpers          import find_serial_ports
from config.config_loader       import get_config, dump_config

log = get_logger(__name__)

# ─── ANSI colour codes ───────────────────────────────────────────────────────
_C = {
    "green":  "\033[32m", "red":    "\033[31m", "yellow": "\033[33m",
    "cyan":   "\033[36m", "blue":   "\033[34m", "purple": "\033[35m",
    "bold":   "\033[1m",  "dim":    "\033[2m",  "reset":  "\033[0m",
}
def _c(t, c): return f"{_C.get(c,'')}{t}{_C['reset']}"
def _ok(m):      print(_c(f"  ✓  {m}", "green"))
def _fail(m):    print(_c(f"  ✗  {m}", "red"))
def _info(m):    print(_c(f"  ▸  {m}", "cyan"))
def _warn(m):    print(_c(f"  !  {m}", "yellow"))
def _section(m): print("\n" + _c(f"  ── {m} ──", "bold"))

# ─── Live event display ───────────────────────────────────────────────────────
# Prints TTS/STT events from background threads without breaking the prompt.
# Uses a lock so concurrent threads don't interleave characters.
_print_lock = threading.Lock()

def _live(icon: str, label: str, text: str, colour: str) -> None:
    """
    Print a live event line from any thread.

    Writes a blank line before and uses \\r to re-draw the terminal line so
    that background thread output doesn't chop up whatever the user is typing.

    Example output:
        🔊 SPEAKING   "Oh! I found you!"
        🎤 HEARD      "hey r seven"
    """
    ts   = time.strftime("%H:%M:%S")
    line = f"\n  {icon}  {_c(f'{label:<9}', colour)}  {_c(ts, 'dim')}  \"{text}\"\n"
    with _print_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def _on_speaking(text: str) -> None:
    """Hook called by TTSManager just before it speaks."""
    _live("🔊", "SPEAKING", text[:80], "cyan")


def _on_heard(text: str) -> None:
    """Hook called by STTManager whenever the mic recognises speech."""
    _live("🎤", "HEARD", text[:80], "yellow")


# ─── Help text ────────────────────────────────────────────────────────────────
HELP_TEXT = """
┌─────────────────────────────────────────────────────────────────────┐
│                   R-7 Droid — Command Console                       │
├─────────────────┬───────────────────────────────────────────────────┤
│ MOVEMENT        │ forward [sec]   backward [sec]                    │
│                 │ left [deg]      right [deg]     stop              │
├─────────────────┼───────────────────────────────────────────────────┤
│ ROOMBA          │ wake   safe   full   beep   clean   dock          │
│                 │ battery   bumpers   mode                          │
├─────────────────┼───────────────────────────────────────────────────┤
│ BEHAVIOURS      │ roam   follow   search   idle                     │
├─────────────────┼───────────────────────────────────────────────────┤
│ HUSKYLENS       │ husky                (one-line sensor status)     │
│                 │ husky-algo <name>    (switch algorithm)           │
│                 │   algorithms: face_recognition  object_tracking   │
│                 │              color_recognition  tag_recognition   │
│                 │              line_tracking  object_recognition    │
├─────────────────┼───────────────────────────────────────────────────┤
│ AI / SPEECH     │ ask <question>   say <text>   ai-status           │
│                 │ mute   unmute                                     │
├─────────────────┼───────────────────────────────────────────────────┤
│ SYSTEM          │ status   config   help   quit                     │
└─────────────────┴───────────────────────────────────────────────────┘

Live feed lines appear automatically:
  🔊 SPEAKING  — everything the droid says out loud
  🎤 HEARD     — everything the microphone picks up (if STT is enabled)
  🎯 HUSKY     — target acquired / lost (fires only on state change)
"""


def _on_husky_target(detected: bool, state) -> None:
    """Fires once when HuskyLens target is acquired or lost."""
    if detected:
        algo  = state.algorithm.replace("_", " ")
        count = state.target_count
        pos   = "left" if state.target_x_offset < -0.2 else "right" if state.target_x_offset > 0.2 else "center"
        _live("🎯", "HUSKY", f"acquired — {algo}, {count} target{'s' if count != 1 else ''}, {pos}", "green")
    else:
        _live("🎯", "HUSKY", "target lost", "yellow")


class DroidConsole:
    """Full-system interactive terminal console."""

    def __init__(self, args: argparse.Namespace) -> None:
        self._args       = args
        self._roomba     = RoombaController()
        self._husky:     HuskyLensManager | None = None
        self._tts        = TTSManager()
        self._stt:       STTManager       | None = None
        self._personality = Personality()
        self._ai         = OllamaClient()
        self._behavior:  BehaviorManager  | None = None
        self._muted      = False

    # ─── Startup ─────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Initialise all subsystems in dependency order."""
        _section("Starting R-7 Droid System")
        cfg = get_config()

        # ── TTS ─────────────────────────────────────────────────────────────
        _info("Starting TTS engine...")
        if cfg["audio"].get("tts_enabled", True):
            if self._tts.start():
                # Hook the live-display callback FIRST so every spoken line
                # shows up in the terminal, regardless of what triggered it.
                self._tts.set_speak_callback(_on_speaking)
                _ok("TTS ready — spoken lines will appear as 🔊 SPEAKING")
            else:
                _warn("TTS failed — speech disabled")
        else:
            _info("TTS disabled in config")

        # ── Roomba ──────────────────────────────────────────────────────────
        _info("Connecting to Roomba...")
        port = getattr(self._args, "port", None)
        if not self._roomba.startup(port):
            _fail("Could not connect to Roomba")
            _warn("Run: python roomba/roomba_test.py  to diagnose")
            return False
        _ok(f"Roomba connected — {self._roomba.state.name} mode")

        # ── HuskyLens ───────────────────────────────────────────────────────
        if not self._args.no_vision:
            _info("Starting HuskyLens sensor...")
            self._husky = HuskyLensManager()
            self._husky.set_target_callback(_on_husky_target)
            if self._husky.start():
                _ok(f"HuskyLens running — algorithm: {self._husky.current_algorithm}")
            else:
                _warn("HuskyLens failed — check wiring and port config")
                self._husky = None

        # ── AI ──────────────────────────────────────────────────────────────
        if not self._args.no_ai:
            _info("Checking AI (Ollama)...")
            model = cfg["ai"].get("model", "llama3.2:1b")
            if self._ai.is_available():
                _ok(f"Ollama ready  model={model}")
            else:
                _warn(f"Ollama not available — canned phrases only")
                _info("Start Ollama:  ollama serve")
                _info(f"Pull model:    ollama pull {model}")

        # ── STT ─────────────────────────────────────────────────────────────
        if cfg["audio"].get("voice_input_enabled", False):
            _info("Starting STT (voice input)...")
            self._stt = STTManager()

            # Interrupt TTS the moment any speech is detected
            self._stt.set_interrupt_callback(self._tts.interrupt)

            # Show everything the mic hears in the terminal live
            self._stt.set_heard_callback(_on_heard)

            # When a wake-word command is recognised, ask AI and speak
            self._stt.set_callback(self._handle_voice_command)

            if self._stt.start():
                wake = cfg["audio"].get("wake_word", "hey r-seven")
                _ok(f"STT running — say \"{wake}\" to speak  (shown as 🎤 HEARD)")
            else:
                _warn("STT failed — voice input disabled")
                self._stt = None
        else:
            _info("Voice input disabled (set voice_input_enabled: true in config)")

        # ── Behaviours ──────────────────────────────────────────────────────
        if self._husky:
            self._behavior = BehaviorManager(
                roomba      = self._roomba,
                husky       = self._husky,
                tts         = self._tts,
                personality = self._personality,
                ai_client   = self._ai if not self._args.no_ai else None,
            )

        # ── Startup greeting ─────────────────────────────────────────────────
        greeting = self._personality.greeting()
        _ok(f"System ready")
        if not self._muted:
            self._tts.speak(greeting)   # triggers 🔊 SPEAKING line automatically

        return True

    # ─── Voice command handler ────────────────────────────────────────────────

    def _handle_voice_command(self, text: str) -> None:
        """
        Called by STTManager when the wake word + command is recognised.
        Asks the AI and speaks the response.
        Canned phrases are blocked while this runs via the _ai_busy flag
        in BehaviorManager.
        """
        log.info("Voice command: %s", text)

        # Try AI first
        if not self._args.no_ai and self._ai.is_available():
            response = self._ai.ask(text)
            if response:
                filtered = self._personality.filter_ai_response(response)
                self._tts.speak(filtered, priority=True)
                self._personality.mark_spoke()
                return

        # Fallback: canned phrase
        phrase = self._personality.react("confused")
        self._tts.speak(phrase, priority=True)
        self._personality.mark_spoke()

    # ─── Shutdown ─────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Clean shutdown — stop all subsystems in reverse order."""
        _section("Shutting down")
        if self._behavior:
            self._behavior.stop()
        if self._husky:
            self._husky.stop()
        if self._stt:
            self._stt.stop()
        self._tts.stop()
        self._roomba.shutdown()
        _ok("All systems stopped. Goodbye!")

    # ─── Main loop ────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Block on the interactive prompt until quit."""
        print()
        print(_c("  R-7 Droid — Command Console", "bold"))
        print(_c("  Live events appear automatically as 🔊 / 🎤 lines.", "dim"))
        print(_c("  Type 'help' for all commands.", "dim"))
        print()

        while True:
            try:
                # Build a prompt showing Roomba mode + behaviour state
                r_state = self._roomba.state.name
                b_state = (self._behavior.state.name
                           if self._behavior else "NO_VISION")
                prompt  = (
                    _c(f"[{r_state}]", "cyan") +
                    _c(f"[{b_state}]", "green") +
                    " > "
                )

                raw = input(prompt).strip()
                if not raw:
                    continue

                parts = raw.split(None, 2)
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

    # ─── Command dispatch ─────────────────────────────────────────────────────

    def _dispatch(self, cmd: str, args: list[str]) -> None:
        r = self._roomba

        # ── Movement ────────────────────────────────────────────────────────
        if cmd == "forward":
            dur = float(args[0]) if args else 1.0
            r.forward(dur)
            _ok(f"Forward {dur}s")

        elif cmd == "backward":
            dur = float(args[0]) if args else 1.0
            r.backward(dur)
            _ok(f"Backward {dur}s")

        elif cmd == "left":
            deg = float(args[0]) if args else 90.0
            r.spin_left(deg)
            _ok(f"Spin left ~{deg}°")

        elif cmd == "right":
            deg = float(args[0]) if args else 90.0
            r.spin_right(deg)
            _ok(f"Spin right ~{deg}°")

        elif cmd == "stop":
            r.stop()
            _ok("Stopped")

        # ── Roomba ──────────────────────────────────────────────────────────
        elif cmd == "wake":
            r._serial.wakeup()
            _ok("Wakeup pulse sent")

        elif cmd == "safe":
            if r.set_safe_mode(): _ok("Safe mode")
            else:                 _fail("Mode change failed")

        elif cmd == "full":
            _warn("Full mode disables all safety stops!")
            if input("    Type 'yes' to confirm: ").strip().lower() == "yes":
                r.set_full_mode()
            else:
                _info("Cancelled")

        elif cmd == "beep":
            r.beep()
            _ok("Beep!")

        elif cmd == "clean":
            r.clean()
            _ok("Clean cycle started")

        elif cmd == "dock":
            r.dock()
            _ok("Seeking dock...")

        elif cmd == "battery":
            data = r.read_battery()
            if data:
                _ok(f"Battery: {data['pct']:.1f}%  |  "
                    f"{data['voltage_mv']} mV  |  "
                    f"{data['charge_mah']}/{data['capacity_mah']} mAh")
            else:
                _fail("Could not read battery")

        elif cmd == "bumpers":
            data = r.read_bumpers()
            if data:
                l = _c("HIT", "red") if data["left"]  else "clear"
                rx = _c("HIT", "red") if data["right"] else "clear"
                _ok(f"Left: {l}   Right: {rx}")
            else:
                _fail("Could not read bumpers")

        elif cmd == "mode":
            m = r.read_oi_mode()
            names = {0: "OFF", 1: "PASSIVE", 2: "SAFE", 3: "FULL"}
            _ok(f"OI mode: {names.get(m, '?')} ({m})")

        # ── Behaviours ──────────────────────────────────────────────────────
        elif cmd == "roam":
            if self._behavior:
                self._behavior.force_state(BehaviorState.FREE_ROAM)
                if not (self._behavior._thread and self._behavior._thread.is_alive()):
                    self._behavior.start()
                _ok("Free roam mode")
            else:
                _fail("No HuskyLens — behaviour system not running")

        elif cmd == "follow":
            if self._behavior:
                self._behavior.force_state(BehaviorState.FOLLOW_PERSON)
                _ok("Follow person mode")
            else:
                _fail("No HuskyLens — cannot follow")

        elif cmd == "search":
            if self._behavior:
                self._behavior.force_state(BehaviorState.SEARCH_PERSON)
                _ok("Search mode")
            else:
                _fail("No HuskyLens available")

        elif cmd == "idle":
            if self._behavior:
                self._behavior.stop()
            r.stop()
            _ok("Idle — behaviours stopped, Roomba halted")

        # ── HuskyLens ───────────────────────────────────────────────────────
        elif cmd == "husky":
            if self._husky:
                s = self._husky.get_state()
                tgt  = _c("YES", "green") if s.any_target_detected else _c("no", "dim")
                algo = s.algorithm.replace("_", " ")
                pos  = ""
                if s.any_target_detected:
                    side = ("left" if s.target_x_offset < -0.2
                            else "right" if s.target_x_offset > 0.2
                            else "center")
                    dist = ("close" if s.target_fill > 0.5
                            else "medium" if s.target_fill > 0.2
                            else "far")
                    pos = f"  {side}, {dist}  id={s.target_id}  count={s.target_count}"
                _ok(f"algo={algo}  target={tgt}{pos}  frames={s.frame_count}")
            else:
                _fail("HuskyLens not running")

        elif cmd == "husky-algo":
            if not self._husky:
                _fail("HuskyLens not running")
                return
            name = args[0].lower() if args else ""
            if not name:
                _warn(f"Usage: husky-algo <name>")
                _info(f"Available: {', '.join(ALGO_IDS)}")
                return
            if self._husky.set_algorithm(name):
                _ok(f"Algorithm → {name}")
                _info("Also select the matching algorithm on the HuskyLens screen")
            else:
                _fail(f"Unknown algorithm: {name!r}")
                _info(f"Available: {', '.join(ALGO_IDS)}")

        # ── AI / Speech ──────────────────────────────────────────────────────
        elif cmd == "ask":
            # Manual AI query from the console — bypasses behaviour system
            prompt = " ".join(args).strip() if args else ""
            if not prompt:
                _warn("Usage: ask <your question>")
                return
            _info(f"Asking AI: {prompt}")
            if self._ai.is_available():
                response = self._ai.ask(prompt)
                if response:
                    filtered = self._personality.filter_ai_response(response)
                    # Speak it (triggers 🔊 SPEAKING line automatically)
                    if not self._muted:
                        self._tts.speak(filtered, priority=True)
                    else:
                        # Muted: still show it in the terminal
                        _live("🤖", "AI REPLY", filtered, "purple")
                else:
                    _fail("AI returned empty response")
            else:
                _fail("AI not available — check: ollama serve")

        elif cmd == "say":
            # Force-speak a specific string, bypass AI and personality
            text = " ".join(args).strip() if args else ""
            if not text:
                _warn("Usage: say <text to speak>")
                return
            if self._muted:
                _warn("Muted — not speaking")
            else:
                self._tts.speak(text, priority=True)

        elif cmd == "mute":
            self._muted = True
            _ok("Muted — TTS output suppressed for manual commands")
            _info("(Autonomous behaviour speech is NOT muted)")

        elif cmd == "unmute":
            self._muted = False
            _ok("Unmuted")

        elif cmd == "ai-status":
            info = self._ai.get_model_info()
            avail = _c("available", "green") if info["available"] else _c("offline", "red")
            print(f"\n    Model    : {_c(info['model'], 'cyan')}")
            print(f"    Status   : {avail}")
            print(f"    Host     : {info['host']}")
            print(f"    Timeout  : {info['timeout']}s")
            print()

        # ── System ───────────────────────────────────────────────────────────
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
            _warn(f"Unknown command: '{cmd}'  — type 'help'")

    # ─── Status display ───────────────────────────────────────────────────────

    def _print_status(self) -> None:
        status = self._roomba.get_status()
        _section("System Status")

        # Roomba
        print(f"    Roomba    : {_c(status['state'], 'cyan')}")
        batt_c   = "green" if status["battery_pct"] > 30 else "yellow" if status["battery_pct"] > 10 else "red"
        batt_str = f"{status['battery_pct']:.1f}%"
        print(f"    Battery   : {_c(batt_str, batt_c)}"
              f"  ({status['voltage_mv']} mV)")

        # Behaviour
        if self._behavior:
            b = self._behavior.state.name
            print(f"    Behaviour : {_c(b, 'green')}")
        else:
            print(f"    Behaviour : {_c('not running', 'dim')}")

        # HuskyLens
        if self._husky:
            hs   = self._husky.get_state()
            tgt  = "TARGET" if hs.any_target_detected else "none"
            tgt_c = "green" if hs.any_target_detected else "dim"
            algo = hs.algorithm.replace("_", " ")
            print(f"    HuskyLens : algo={algo}  target={_c(tgt, tgt_c)}"
                  f"  offset={hs.target_x_offset:+.2f}"
                  f"  frames={hs.frame_count}")
        else:
            print(f"    HuskyLens : {_c('not running', 'dim')}")

        # AI
        ai_info = self._ai.get_model_info()
        ai_str  = f"{_c('available', 'green')}  model={ai_info['model']}" \
                  if ai_info["available"] else _c("offline", "yellow")
        print(f"    AI        : {ai_str}")

        # TTS / STT
        spk = _c("speaking", "cyan") if self._tts.is_speaking else "idle"
        mut = _c("MUTED", "yellow") if self._muted else "unmuted"
        print(f"    TTS       : {spk}  [{mut}]")

        stt_str = "enabled" if self._stt else _c("disabled", "dim")
        print(f"    STT       : {stt_str}")
        print()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="R-7 Droid — interactive command console",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--no-vision", action="store_true", help="Skip HuskyLens vision sensor")
    parser.add_argument("--no-ai",     action="store_true", help="Skip Ollama AI")
    parser.add_argument("--debug",     action="store_true", help="Verbose logging")
    parser.add_argument("--port",      default=None,        help="Serial port override")
    args = parser.parse_args()

    if args.debug:
        set_global_level("DEBUG")

    console = DroidConsole(args)
    if console.start():
        console.run()
    else:
        print(_c("\n  Startup failed — check logs/ for details\n", "red"))
        sys.exit(1)
