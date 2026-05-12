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

from typing import Any, Optional
from roomba.controller import RoombaController


def build_context(
    vision:  Any                        = None,   # HuskyLensState or any duck-compatible
    roomba:  Optional[RoombaController] = None,
    extra:   str = "",
) -> str:
    """
    Build a compact context string from available system state.

    Parameters
    ----------
    vision : HuskyLensState (or any object with person_detected/target_x_offset/target_fill)
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
    # Deliberately omit mode names like "safe mode" / "full mode" —
    # small LLMs treat those as screenplay stage directions and start
    # generating roleplay text.
    if roomba is not None:
        status = roomba.get_status()
        if status["battery_pct"] > 0:
            parts.append(f"battery {status['battery_pct']:.0f}%")
        if status["bump_left"] or status["bump_right"]:
            parts.append("obstacle nearby")

    # ── Extra ─────────────────────────────────────────────────────────
    if extra:
        parts.append(extra)

    return ". ".join(parts) + "." if parts else ""
