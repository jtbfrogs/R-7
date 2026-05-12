"""
diagnostics/check_all.py
─────────────────────────
Run ALL diagnostic checks and print a health summary.
Start here to figure out which subsystems are ready.

Usage
─────
    python diagnostics/check_all.py
    python diagnostics/check_all.py --port /dev/ttyUSB0
"""

import sys
import os
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utilities.helpers import check_import, format_check_result, find_serial_ports, best_guess_roomba_port
import argparse

def _c(t,c):
    codes={"green":"\033[32m","red":"\033[31m","yellow":"\033[33m",
           "cyan":"\033[36m","bold":"\033[1m","reset":"\033[0m"}
    return f"{codes.get(c,'')}{t}{codes['reset']}"


def main(port: str | None = None) -> None:
    print()
    print(_c("  R-7 Droid — System Health Check", "bold"))
    print(_c("  ─────────────────────────────────", "cyan"))
    print()

    results: list[tuple[str, bool, str]] = []

    # ── Python version ────────────────────────────────────────────────────────
    ver = sys.version_info
    ok  = ver.major == 3 and ver.minor >= 10
    results.append(("Python version", ok, f"{ver.major}.{ver.minor}.{ver.micro}"))

    # ── Core dependencies ─────────────────────────────────────────────────────
    deps = [
        ("pyserial",        "serial",   "pip install pyserial"),
        ("PyYAML",          "yaml",     "pip install pyyaml"),
        ("numpy",           "numpy",    "pip install numpy"),
        ("pyttsx3",         "pyttsx3",  "pip install pyttsx3"),
        ("httpx",           "httpx",    "pip install httpx"),
    ]

    print("  Core dependencies:")
    for name, module, fix in deps:
        found = check_import(module)
        results.append((name, found, "installed" if found else f"MISSING — {fix}"))
        print(format_check_result(name, found, "installed" if found else "MISSING"))

    # ── Optional dependencies ─────────────────────────────────────────────────
    print("\n  Optional dependencies:")
    opt_deps = [
        ("torch (PyTorch)",    "torch",       "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118"),
        ("torchvision",        "torchvision", "pip install torchvision"),
        ("vosk (offline STT)", "vosk",        "pip install vosk sounddevice"),
        ("sounddevice",        "sounddevice", "pip install sounddevice"),
        ("piper-tts",          "piper",       "pip install piper-tts"),
        ("SpeechRecognition",  "speech_recognition", "pip install SpeechRecognition"),
    ]
    for name, module, fix in opt_deps:
        found = check_import(module)
        results.append((name + " (opt)", found, "installed" if found else f"optional — {fix}"))
        print(format_check_result(name, found, "installed" if found else "not installed"))

    # ── Serial port check ─────────────────────────────────────────────────────
    print("\n  Serial / Roomba:")
    ports = find_serial_ports()
    ports_found = len(ports) > 0
    results.append(("Serial ports", ports_found, ", ".join(ports) if ports else "none found"))
    print(format_check_result("Serial ports found", ports_found, ", ".join(ports) or "none"))

    if port or best_guess_roomba_port():
        target = port or best_guess_roomba_port()
        # Quick open test
        try:
            import serial as _s
            p = _s.Serial(target, 115200, timeout=0.5)
            p.close()
            results.append(("Target port open", True, target))
            print(format_check_result("Can open port", True, target))
        except Exception as e:
            results.append(("Target port open", False, str(e)[:50]))
            print(format_check_result("Can open port", False, str(e)[:50]))
    else:
        print(format_check_result("Target port", False, "no port detected"))

    # ── HuskyLens check ───────────────────────────────────────────────────────
    print("\n  HuskyLens 2:")
    hl_ports = [p for p in ports if "USB" in p or "ACM" in p]
    hl_port  = hl_ports[1] if len(hl_ports) >= 2 else (hl_ports[0] if hl_ports else None)
    if hl_port:
        try:
            import serial as _s
            from huskylens.protocol import HuskyProtocol
            import time as _t
            hl_ser = _s.Serial(hl_port, baudrate=9600, timeout=0.5)
            _t.sleep(0.3)
            hl_proto = HuskyProtocol(hl_ser)
            hl_ok = any(hl_proto.knock() for _ in range(3))
            hl_ser.close()
            results.append(("HuskyLens knock", hl_ok,
                             "responded" if hl_ok else "no response — check wiring/baud"))
            print(format_check_result("HuskyLens knock", hl_ok,
                                      f"{hl_port} — {'OK' if hl_ok else 'no response'}"))
        except Exception as e:
            results.append(("HuskyLens", False, str(e)[:50]))
            print(format_check_result("HuskyLens", False, str(e)[:50]))
    else:
        print(format_check_result("HuskyLens port", False, "no USB-UART adapter found"))
    print(format_check_result("HuskyLens full test", True,
                               "run: python diagnostics/check_huskylens.py"))

    # ── Ollama check ──────────────────────────────────────────────────────────
    print("\n  AI (Ollama):")
    try:
        import httpx as _hx
        r = _hx.get("http://localhost:11434/api/tags", timeout=2.0)
        r.raise_for_status()
        data   = r.json()
        models = [m["name"] for m in data.get("models", [])]
        ollama_ok = True
        detail = f"running — models: {models or '(none loaded)'}"
    except Exception as e:
        ollama_ok = False
        detail = f"not running ({str(e)[:40]})"
    results.append(("Ollama server", ollama_ok, detail))
    print(format_check_result("Ollama server", ollama_ok, detail))

    # ── TTS quick test ────────────────────────────────────────────────────────
    print("\n  Audio:")
    tts_ok = check_import("pyttsx3")
    print(format_check_result("pyttsx3 TTS", tts_ok, "installed" if tts_ok else "missing"))

    # Check espeak (needed by pyttsx3 on Linux)
    espeak = subprocess.run(["which", "espeak"], capture_output=True)
    espeak_ok = espeak.returncode == 0
    print(format_check_result("espeak (Linux TTS)", espeak_ok,
                               "found" if espeak_ok else "missing — sudo apt install espeak"))

    # ── Config check ─────────────────────────────────────────────────────────
    print("\n  Configuration:")
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "default_config.yaml")
    cfg_ok   = os.path.exists(cfg_path)
    print(format_check_result("default_config.yaml", cfg_ok,
                               "found" if cfg_ok else "MISSING — repo incomplete"))

    local_cfg = cfg_path.replace("default_config", "local_config")
    local_ok  = os.path.exists(local_cfg)
    print(format_check_result("local_config.yaml", local_ok,
                               "found (overrides active)" if local_ok else "not present (using defaults)"))

    # ── Logs directory ────────────────────────────────────────────────────────
    logs_ok = os.path.isdir(os.path.join(os.path.dirname(__file__), "..", "logs"))
    print(format_check_result("logs/ directory", logs_ok, "exists" if logs_ok else "missing"))

    # ── Final summary ────────────────────────────────────────────────────────
    critical = [("Python version", "Serial ports found", "Can open port")]
    critical_results = [(n,ok) for (n,ok,_) in results if n in [
        "Python version","pyserial","PyYAML","pyttsx3"
    ]]
    failed_critical = [n for n,ok in critical_results if not ok]

    print()
    print(_c("  ── Summary ──", "bold"))
    if not failed_critical:
        print(_c("  ✓  Core dependencies OK — system can start", "green"))
    else:
        print(_c(f"  ✗  Missing critical packages: {', '.join(failed_critical)}", "red"))
        print("     Run:  bash scripts/install_dependencies.sh")

    if not ollama_ok:
        print(_c("  !  Ollama not running — AI responses disabled until started", "yellow"))
        print("     Run:  ollama serve   (or install from https://ollama.com)")

    print()
    print("  Next steps:")
    print(_c("    python diagnostics/check_roomba_serial.py   (Roomba serial test)", "cyan"))
    print(_c("    python diagnostics/check_huskylens.py       (HuskyLens sensor test)", "cyan"))
    print(_c("    python roomba/roomba_test.py                (interactive Roomba test)", "cyan"))
    print(_c("    python commands/command_console.py          (full system console)", "cyan"))
    print(_c("    python main.py                              (launch droid)", "cyan"))
    print(_c("    python main.py --no-vision                  (launch without HuskyLens)", "cyan"))
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="R-7 system health check")
    parser.add_argument("--port", default=None, help="Serial port to test")
    args = parser.parse_args()
    main(args.port)
