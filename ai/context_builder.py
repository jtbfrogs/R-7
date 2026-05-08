"""
ai/context_builder.py
──────────────────────
Assembles a context string from all available sensor/vision/state data
before passing it to the AI model.

The AI model has a very small context window — so this builder is
careful to produce MINIMAL but informative context strings.

Example output
──────────────
    "Person visible left. Battery 78%. Safe mode. No obstacle."
"""

from typing import Optional
from vision.vision_manager import VisionState
from roomba.controller import RoombaController, ControllerState


def build_context(
    vision:  Optional[VisionState]    = None,
    roomba:  Optional[RoombaController] = None,
    extra:   str = "",
) -> str:
    """
    Build a compact context string from available system state.

    Parameters
    ----------
    vision : latest VisionState from VisionManager
    roomba : the RoombaController (for mode, battery, bumpers)
    extra  : any freeform string to append

    Returns
    -------
    Short context string for injection into the AI prompt.
    """
    parts: list[str] = []

    # ── Vision context ────────────────────────────────────────────────
    if vision is not None:
        if vision.person_detected:
            offset = vision.target_x_offset
            if offset < -0.2:
                direction = "left"
            elif offset > 0.2:
                direction = "right"
            else:
                direction = "ahead"
            fill = vision.target_fill
            if fill > 0.5:
                distance = "close"
            elif fill > 0.2:
                distance = "medium"
            else:
                distance = "far"
            parts.append(f"Person {distance} {direction}")
        else:
            parts.append("No person visible")

    # ── Roomba state ──────────────────────────────────────────────────
    if roomba is not None:
        parts.append(f"{roomba.state.name.lower()} mode")
        status = roomba.get_status()
        if status["battery_pct"] > 0:
            parts.append(f"battery {status['battery_pct']:.0f}%")
        if status["bump_left"] or status["bump_right"]:
            parts.append("bump sensor triggered")

    # ── Extra ─────────────────────────────────────────────────────────
    if extra:
        parts.append(extra)

    return ". ".join(parts) + "." if parts else ""
