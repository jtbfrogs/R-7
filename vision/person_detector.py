"""
vision/person_detector.py
──────────────────────────
Detects people (full-body) and faces in camera frames.

Two detection stages
─────────────────────
1. FAST:  OpenCV HOG person detector + Haar face cascade.
          Works with just `opencv-python` — no model downloads needed.
          Good enough for "is there a person in front of me?" decisions.

2. BETTER (optional): If PyTorch + torchvision are installed, we can use
          a MobileNet SSD or YOLOv5n (nano) model for much better accuracy.
          Enabled automatically if available.

Design
──────
  • Stateless: just takes a frame in, returns detections out.
  • All thresholds configurable via default_config.yaml.
  • Frame skipping built in: only run detection every N frames.
  • Returns structured DetectionResult objects, not raw tuples.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import cv2
except ImportError:
    raise ImportError("opencv-python required: pip install opencv-python")

import numpy as np
from utilities.logger import get_logger
from utilities.constants import (
    DETECTION_CONFIDENCE_PERSON, DETECTION_CONFIDENCE_FACE,
    FOLLOW_DISTANCE_THRESHOLD, FRAME_SKIP_DETECTION,
)
from config.config_loader import get_config

log = get_logger(__name__)


@dataclass
class BoundingBox:
    """A detected region in the frame."""
    x: int          # left edge (pixels)
    y: int          # top edge (pixels)
    w: int          # width (pixels)
    h: int          # height (pixels)
    confidence: float = 1.0

    @property
    def cx(self) -> int:
        """Horizontal centre of the box."""
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        """Vertical centre of the box."""
        return self.y + self.h // 2

    @property
    def area(self) -> int:
        return self.w * self.h

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


@dataclass
class DetectionResult:
    """
    Complete detection output for a single frame.
    Passed to the behaviour system to decide what the robot should do.
    """
    timestamp: float                        = field(default_factory=time.time)
    persons:   list[BoundingBox]            = field(default_factory=list)
    faces:     list[BoundingBox]            = field(default_factory=list)
    frame_w:   int                          = 640
    frame_h:   int                          = 480

    @property
    def person_detected(self) -> bool:
        return len(self.persons) > 0

    @property
    def face_detected(self) -> bool:
        return len(self.faces) > 0

    @property
    def any_target_detected(self) -> bool:
        """
        True if either a full-body HOG detection OR a face detection exists.

        Use this — not person_detected — for behaviour decisions.

        Why: HOG is trained on upright pedestrians in outdoor scenes.
        It frequently misses people who are sitting, partially visible,
        or too close to the camera.  The Haar face cascade works at
        much shorter range and is far more reliable indoors.
        Both detections share the same primary_target logic, so following
        a face is just as valid as following a full body.
        """
        return self.person_detected or self.face_detected

    @property
    def best_person(self) -> Optional[BoundingBox]:
        """Return the largest (closest) detected person."""
        if not self.persons:
            return None
        return max(self.persons, key=lambda b: b.area)

    @property
    def best_face(self) -> Optional[BoundingBox]:
        """Return the most confident face detection."""
        if not self.faces:
            return None
        return max(self.faces, key=lambda b: b.confidence)

    @property
    def primary_target(self) -> Optional[BoundingBox]:
        """Best face if available, otherwise best person."""
        return self.best_face or self.best_person

    def target_x_offset(self) -> float:
        """
        Horizontal offset of the primary target from frame centre.
        Returns a value from -1.0 (far left) to +1.0 (far right).
        0.0 means target is centred.
        """
        target = self.primary_target
        if target is None:
            return 0.0
        centre_x = self.frame_w / 2
        return (target.cx - centre_x) / (self.frame_w / 2)

    def target_fill_ratio(self) -> float:
        """
        How much of the frame width the primary target fills.
        Used to decide "close enough" threshold.
        Returns 0.0 if no target.
        """
        target = self.primary_target
        if target is None:
            return 0.0
        return target.w / self.frame_w


class PersonDetector:
    """
    Detects persons and faces in camera frames.

    Supports two backends:
      - 'hog'  : OpenCV HOG pedestrian + Haar cascade (always available)
      - 'torch': PyTorch MobileNet SSD (better, needs torch + torchvision)

    The backend is selected automatically based on what's installed.
    You can force 'hog' in the config if you want to skip torch even if available.
    """

    def __init__(self):
        self._cfg          = get_config()
        self._vis_cfg      = self._cfg["vision"]
        self._frame_skip   = self._vis_cfg.get("detection_frame_skip", FRAME_SKIP_DETECTION)
        self._person_conf  = self._vis_cfg.get("person_confidence", DETECTION_CONFIDENCE_PERSON)
        self._face_conf    = self._vis_cfg.get("face_confidence",   DETECTION_CONFIDENCE_FACE)
        self._enable_person = self._vis_cfg.get("enable_person_detection", True)
        self._enable_face   = self._vis_cfg.get("enable_face_detection",   True)

        self._frame_counter = 0
        self._last_result:  Optional[DetectionResult] = None

        # Initialise detectors
        self._hog  = self._init_hog()
        self._face_cascade = self._init_face_cascade()
        self._torch_detector = self._init_torch()

        backend = "torch" if self._torch_detector else "hog"
        log.info("Person detector initialised (backend=%s, frame_skip=%d)",
                 backend, self._frame_skip)

    # ─── Initialisation ──────────────────────────────────────────────────────

    def _init_hog(self) -> cv2.HOGDescriptor:
        """
        OpenCV HOG descriptor pre-trained for pedestrian detection.
        This is the fallback — always available.
        """
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        return hog

    def _init_face_cascade(self) -> Optional[cv2.CascadeClassifier]:
        """
        Haar cascade for frontal face detection.
        Bundled with opencv-python — no extra download needed.
        """
        # OpenCV ships the cascade XML files with the package
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if not os.path.exists(cascade_path):
            log.warning("Face cascade XML not found at %s — face detection disabled", cascade_path)
            return None
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            log.warning("Face cascade failed to load — face detection disabled")
            return None
        log.debug("Face cascade loaded OK")
        return cascade

    def _init_torch(self):
        """
        Optional: load a PyTorch MobileNet SSD for better person detection.
        Returns the model if torch + torchvision are available, else None.
        """
        try:
            import torch
            import torchvision
            from torchvision.models.detection import ssdlite320_mobilenet_v3_large
            from torchvision.models.detection import SSDLite320_MobileNet_V3_Large_Weights

            log.info("PyTorch detected — loading MobileNet SSD for person detection...")
            weights = SSDLite320_MobileNet_V3_Large_Weights.DEFAULT
            model   = ssdlite320_mobilenet_v3_large(weights=weights)
            model.eval()

            # Use GPU if available
            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model = model.to(self._device)

            gpu_label = f"GPU ({torch.cuda.get_device_name(0)})" if torch.cuda.is_available() else "CPU"
            log.info("MobileNet SSD loaded on %s", gpu_label)
            return model

        except ImportError:
            log.info("PyTorch not installed — using OpenCV HOG detector (totally fine)")
            return None
        except Exception as e:
            log.warning("Failed to load PyTorch detector: %s — falling back to HOG", e)
            return None

    # ─── Detection ───────────────────────────────────────────────────────────

    def detect(self, frame: np.ndarray) -> DetectionResult:
        """
        Run detection on `frame`.

        Frame-skipping: if this is not a detection frame, returns the cached
        result from the last detection run.  This keeps CPU usage manageable.

        Parameters
        ----------
        frame : BGR numpy array from CameraManager

        Returns
        -------
        DetectionResult
        """
        self._frame_counter += 1
        h, w = frame.shape[:2]

        # Return cached result on skip frames
        if self._frame_counter % self._frame_skip != 0:
            if self._last_result is not None:
                return self._last_result
            # No cached result yet — do detection anyway
            pass

        persons: list[BoundingBox] = []
        faces:   list[BoundingBox] = []

        # Person detection
        if self._enable_person:
            if self._torch_detector:
                persons = self._detect_persons_torch(frame)
            else:
                persons = self._detect_persons_hog(frame)

        # Face detection (always uses cascade for speed)
        if self._enable_face:
            faces = self._detect_faces(frame)

        result = DetectionResult(
            persons  = persons,
            faces    = faces,
            frame_w  = w,
            frame_h  = h,
        )
        self._last_result = result
        return result

    def _detect_persons_hog(self, frame: np.ndarray) -> list[BoundingBox]:
        """HOG person detection — slower than YOLO but zero dependencies.

        Robustness notes
        ─────────────────
        detectMultiScale() returns (rects, weights) when detections exist, but
        its exact shape changed across OpenCV versions:

          Older OpenCV : weights shape (N, 1)  → iterating gives shape-(1,) arrays
                         so weight[0] worked fine.
          Newer OpenCV : weights shape (N,)    → iterating gives bare scalars
                         (0-d arrays), so weight[0] raises IndexError.

        We use float(np.squeeze(weight)) which works for both shapes,
        plus a guard for the empty-detection case where the call may
        return an empty tuple () rather than two empty arrays.
        """
        # Downscale for speed — HOG is expensive at full resolution
        small   = cv2.resize(frame, (320, 240))
        scale_x = frame.shape[1] / 320
        scale_y = frame.shape[0] / 240

        raw = self._hog.detectMultiScale(
            small,
            winStride=(8, 8),
            padding=(4, 4),
            scale=1.05,
        )

        # Guard: no detections → raw is () or (empty_array, empty_array)
        if raw is None or len(raw) != 2:
            return []
        rects, weights = raw
        if not isinstance(rects, np.ndarray) or len(rects) == 0:
            return []

        boxes = []
        for i, (x, y, w, h) in enumerate(rects):
            # Flatten to scalar regardless of whether weights is (N,) or (N,1)
            raw_weight = float(np.squeeze(weights[i]))

            # HOG detectMultiScale weights are NOT probabilities.
            # They are raw SVM margin values, typically 0.0 – 3.0.
            # We convert to a 0–1 confidence for display, but filter on
            # a fixed RAW threshold of 0.3 which accepts most real detections
            # while rejecting the noisiest false positives.
            # (The config person_confidence value is used for the Torch backend
            # where scores genuinely are 0–1 probabilities.)
            HOG_RAW_THRESHOLD = 0.3
            if raw_weight < HOG_RAW_THRESHOLD:
                continue

            normalised_conf = min(raw_weight / 3.0, 1.0)   # 0–1 for display
            # Scale coordinates back to original frame size
            boxes.append(BoundingBox(
                x=int(x * scale_x), y=int(y * scale_y),
                w=int(w * scale_x), h=int(h * scale_y),
                confidence=normalised_conf,
            ))
        return boxes

    def _detect_persons_torch(self, frame: np.ndarray) -> list[BoundingBox]:
        """MobileNet SSD person detection — better accuracy than HOG."""
        import torch
        from torchvision.transforms import functional as F

        # Convert BGR → RGB → tensor
        rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        tensor = F.to_tensor(rgb).unsqueeze(0).to(self._device)

        with torch.no_grad():
            predictions = self._torch_detector(tensor)[0]

        boxes = []
        h, w = frame.shape[:2]
        PERSON_CLASS = 1   # COCO class 1 = person

        for box, label, score in zip(
            predictions["boxes"], predictions["labels"], predictions["scores"]
        ):
            if int(label) != PERSON_CLASS:
                continue
            conf = float(score)
            if conf < self._person_conf:
                continue
            x1, y1, x2, y2 = box.cpu().numpy()
            boxes.append(BoundingBox(
                x=int(x1), y=int(y1),
                w=int(x2 - x1), h=int(y2 - y1),
                confidence=conf,
            ))
        return boxes

    def _detect_faces(self, frame: np.ndarray) -> list[BoundingBox]:
        """Haar cascade face detection."""
        if self._face_cascade is None:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Equalise histogram for better detection in varying lighting
        gray = cv2.equalizeHist(gray)

        raw = self._face_cascade.detectMultiScale(
            gray,
            scaleFactor  = 1.1,
            minNeighbors = 5,
            minSize      = (40, 40),
        )

        if not isinstance(raw, np.ndarray) or len(raw) == 0:
            return []

        return [BoundingBox(x=int(x), y=int(y), w=int(w), h=int(h))
                for (x, y, w, h) in raw]

    # ─── Debug visualisation ──────────────────────────────────────────────────

    def draw_detections(self, frame: np.ndarray, result: DetectionResult) -> np.ndarray:
        """
        Draw bounding boxes onto a copy of the frame for debug display.
        Does NOT modify the original frame.
        """
        out = frame.copy()
        for p in result.persons:
            cv2.rectangle(out, (p.x, p.y), (p.x+p.w, p.y+p.h), (0, 255, 0), 2)
            cv2.putText(out, f"person {p.confidence:.2f}",
                        (p.x, p.y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)
        for f in result.faces:
            cv2.rectangle(out, (f.x, f.y), (f.x+f.w, f.y+f.h), (255, 100, 0), 2)
            cv2.putText(out, "face",
                        (f.x, f.y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,100,0), 1)
        # Draw frame centre crosshair
        cx, cy = out.shape[1] // 2, out.shape[0] // 2
        cv2.line(out, (cx - 20, cy), (cx + 20, cy), (200, 200, 200), 1)
        cv2.line(out, (cx, cy - 20), (cx, cy + 20), (200, 200, 200), 1)
        return out
