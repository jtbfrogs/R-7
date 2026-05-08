"""
diagnostics/check_camera.py
────────────────────────────
Standalone camera test.  Opens the webcam, shows a live feed window
for 5 seconds, and reports resolution/fps.

Usage
─────
    python diagnostics/check_camera.py
    python diagnostics/check_camera.py --index 1     # try second camera
    python diagnostics/check_camera.py --no-window   # headless check only
"""

import sys, os, time, argparse
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def run(index: int = 0, show_window: bool = True) -> bool:
    try:
        import cv2
    except ImportError:
        print("  ✗  opencv-python not installed.  Run: pip install opencv-python")
        return False

    print(f"\n  Testing camera index {index}...")
    cap = cv2.VideoCapture(index)

    if not cap.isOpened():
        print(f"  ✗  Cannot open camera {index}")
        print("     Try a different --index value")
        print("     Check: ls /dev/video*")
        return False

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    f = cap.get(cv2.CAP_PROP_FPS)
    print(f"  ✓  Camera {index} opened: {w}×{h} @ {f:.1f} fps")

    if show_window:
        print("     Showing live feed for 5 seconds — press 'q' to quit early...")
        end = time.time() + 5
        while time.time() < end:
            ret, frame = cap.read()
            if not ret:
                break
            cv2.putText(frame, f"Camera {index}  {w}x{h}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
            cv2.imshow("Camera Test — press q to close", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        cv2.destroyAllWindows()

    cap.release()
    print("  ✓  Camera test passed\n")
    return True

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--index",     type=int, default=0)
    p.add_argument("--no-window", action="store_true")
    a = p.parse_args()
    sys.exit(0 if run(a.index, not a.no_window) else 1)
