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
        ("pyserial",        "serial",              "pip install pyserial"),
        ("PyYAML",          "yaml",                "pip install pyyaml"),
        ("opencv-python",   "cv2",                 "pip install opencv-python"),
        ("numpy",           "numpy",               "pip install numpy"),
        ("pyttsx3",         "pyttsx3",             "pip install pyttsx3"),
        ("httpx",           "httpx",               "pip install httpx"),
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

    # ── Camera check ──────────────────────────────────────────────────────────
    print("\n  Camera:")
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        cam_ok = cap.isOpened()
        cap.release()
        results.append(("Camera /dev/video0", cam_ok, "opened OK" if cam_ok else "cannot open"))
        print(format_check_result("Camera (index 0)", cam_ok, "opened OK" if cam_ok else "cannot open"))
    except Exception as e:
        results.append(("Camera", False, str(e)[:40]))
        print(format_check_result("Camera", False, str(e)[:40]))

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

    # ── GPU check ────────────────────────────────────────────────────────────
    print("\n  GPU (optional):")
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        if cuda_ok:
            name = torch.cuda.get_device_name(0)
            detail = f"CUDA available — {name}"
        else:
            detail = "CUDA not available (CPU mode)"
        print(format_check_result("CUDA/GPU", cuda_ok, detail))
    except ImportError:
        print(format_check_result("CUDA/GPU", False, "torch not installed"))

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
    critical = [("Python version","Serial ports found","Can open port","Camera /dev/video0")]
    critical_results = [(n,ok) for (n,ok,_) in results if n in [
        "Python version","pyserial","PyYAML","opencv-python","pyttsx3"
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
    print(_c("    python diagnostics/check_roomba_serial.py   (test serial)", "cyan"))
    print(_c("    python roomba/roomba_test.py                (interactive Roomba test)", "cyan"))
    print(_c("    python commands/command_console.py          (full system console)", "cyan"))
    print(_c("    python main.py                              (launch droid)", "cyan"))
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="R-7 system health check")
    parser.add_argument("--port", default=None, help="Serial port to test")
    args = parser.parse_args()
    main(args.port)
