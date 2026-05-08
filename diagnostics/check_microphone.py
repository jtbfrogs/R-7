"""
diagnostics/check_microphone.py
────────────────────────────────
Test microphone input — records 3 seconds and reports audio levels.

Usage
─────
    python diagnostics/check_microphone.py
"""

import sys, os, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def run() -> bool:
    print("\n  Testing microphone...")
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        print("  ✗  sounddevice or numpy not installed")
        print("     Run: pip install sounddevice numpy")
        return False

    duration = 3.0
    sr       = 16000
    print(f"  Recording {duration}s of audio — speak into your microphone...")

    try:
        audio = sd.rec(int(sr * duration), samplerate=sr, channels=1, dtype="float32")
        sd.wait()
        rms = float(np.sqrt(np.mean(audio ** 2)))
        peak = float(np.max(np.abs(audio)))
        print(f"  ✓  Recorded {duration}s  |  RMS level: {rms:.4f}  |  Peak: {peak:.4f}")
        if rms < 0.001:
            print("  !  Very low audio level — check microphone is not muted")
        else:
            print("  ✓  Microphone test passed\n")
        return True
    except Exception as e:
        print(f"  ✗  Microphone error: {e}")
        print("     Check: arecord -l  (list recording devices)")
        return False

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
