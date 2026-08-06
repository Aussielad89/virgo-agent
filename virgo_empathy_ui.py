"""
virgo_empathy_ui — Empathy-adaptive UI for Virgo Desktop.

Maps the agent's empathy state (frustration, confidence, curiosity)
to real-time visual parameters: accent color saturation, animation
speed, toast duration, sidebar expansion, and notification frequency.

The UI becomes calmer when the agent is frustrated, and more energetic
when it's confident — creating an empathy mirror between the agent's
internal state and the user's environment.
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _log import log

EMPATHY_UI_DIR = HERE / ".virgo_empathy_ui"
EMPATHY_UI_DIR.mkdir(exist_ok=True)
EMPATHY_UI_FILE = EMPATHY_UI_DIR / "history.json"


@dataclass
class EmpathyMetrics:
    frustration: float = 0.0
    confidence: float = 0.0
    curiosity: float = 0.0
    mood: str = "neutral"
    tone: str = "neutral"
    risk_appetite: str = "medium"
    sentiment_score: float = 0.0


@dataclass
class UIAdaptation:
    accent_saturation: float = 1.0
    animation_speed: float = 1.0
    toast_duration_ms: int = 3500
    sidebar_expanded: bool = False
    notification_frequency: float = 1.0
    glow_intensity: float = 0.0
    border_radius: int = 6
    font_size_scale: float = 1.0


def _load_empathy() -> dict[str, Any]:
    emp_file = HERE / ".virgo_empathy.json"
    if emp_file.exists():
        try:
            return json.loads(emp_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def compute_adaptation(empathy: dict[str, Any] | None = None) -> UIAdaptation:
    if empathy is None:
        empathy = _load_empathy()

    sentiment = empathy.get("sentiment_score", 0.0)
    stress = empathy.get("stress_signals", 0)
    mood = empathy.get("mood", "neutral")
    tone = empathy.get("tone", "neutral")

    frustration = 0.0
    confidence = 0.0
    curiosity = 0.0

    if mood == "stressed" or tone == "cautious":
        frustration = 0.8
        confidence = 0.2
    elif mood == "frustrated" or tone == "empathetic":
        frustration = 0.6
        confidence = 0.3
    elif mood == "happy" or tone == "playful":
        frustration = 0.1
        confidence = 0.9
        curiosity = 0.7
    else:
        frustration = 0.3
        confidence = 0.5
        curiosity = 0.4

    frustration = max(0.0, min(1.0, frustration + stress * 0.1))
    confidence = max(0.0, min(1.0, confidence - stress * 0.05))
    curiosity = max(0.0, min(1.0, curiosity))

    # Compute adaptation parameters
    # Frustration → calmer UI
    accent_sat = 1.0 - frustration * 0.5
    anim_speed = 1.0 - frustration * 0.4
    toast_dur = int(3500 + frustration * 3000)
    sidebar_expanded = frustration < 0.5
    notif_freq = 1.0 - frustration * 0.6
    glow = frustration * 0.3
    border_r = max(2, 6 - int(frustration * 4))
    font_scale = 1.0 - frustration * 0.05

    # Confidence → more energetic UI
    accent_sat += confidence * 0.3
    anim_speed += confidence * 0.3
    toast_dur = max(1500, toast_dur - int(confidence * 1000))
    glow += confidence * 0.2

    # Curiosity → more expansive UI
    sidebar_expanded = sidebar_expanded or curiosity > 0.5
    notif_freq += curiosity * 0.3

    accent_sat = max(0.3, min(1.5, accent_sat))
    anim_speed = max(0.4, min(2.0, anim_speed))

    return UIAdaptation(
        accent_saturation=round(accent_sat, 2),
        animation_speed=round(anim_speed, 2),
        toast_duration_ms=toast_dur,
        sidebar_expanded=sidebar_expanded,
        notification_frequency=round(notif_freq, 2),
        glow_intensity=round(glow, 2),
        border_radius=border_r,
        font_size_scale=round(font_scale, 2),
    )


def get_empathy_state() -> EmpathyMetrics:
    empathy = _load_empathy()
    return EmpathyMetrics(
        frustration=empathy.get("frustration", 0.0),
        confidence=empathy.get("confidence", 0.0),
        curiosity=empathy.get("curiosity", 0.0),
        mood=empathy.get("mood", "neutral"),
        tone=empathy.get("tone", "neutral"),
        risk_appetite=empathy.get("risk_appetite", "medium"),
        sentiment_score=empathy.get("sentiment_score", 0.0),
    )


def adaptation_history(limit: int = 20) -> list[dict[str, Any]]:
    if not EMPATHY_UI_FILE.exists():
        return []
    try:
        data = json.loads(EMPATHY_UI_FILE.read_text(encoding="utf-8"))
        return data[-limit:]
    except Exception:
        return []


def save_adaptation(adapt: UIAdaptation) -> None:
    try:
        history = adaptation_history(limit=100)
        history.append({
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "adaptation": {
                "accent_saturation": adapt.accent_saturation,
                "animation_speed": adapt.animation_speed,
                "toast_duration_ms": adapt.toast_duration_ms,
                "sidebar_expanded": adapt.sidebar_expanded,
                "notification_frequency": adapt.notification_frequency,
                "glow_intensity": adapt.glow_intensity,
                "border_radius": adapt.border_radius,
                "font_size_scale": adapt.font_size_scale,
            },
        })
        EMPATHY_UI_FILE.write_text(
            json.dumps(history[-100:], indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def reset_adaptation() -> None:
    try:
        if EMPATHY_UI_FILE.exists():
            EMPATHY_UI_FILE.unlink()
    except Exception:
        pass


def cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Virgo Empathy UI")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("adapt", help="Compute current UI adaptation")
    sub.add_parser("state", help="Show empathy state")
    sub.add_parser("history", help="Show adaptation history")
    sub.add_parser("reset", help="Reset adaptation history")
    args = p.parse_args()
    if args.command == "adapt":
        adapt = compute_adaptation()
        print(json.dumps({
            "accent_saturation": adapt.accent_saturation,
            "animation_speed": adapt.animation_speed,
            "toast_duration_ms": adapt.toast_duration_ms,
            "sidebar_expanded": adapt.sidebar_expanded,
            "notification_frequency": adapt.notification_frequency,
            "glow_intensity": adapt.glow_intensity,
            "border_radius": adapt.border_radius,
            "font_size_scale": adapt.font_size_scale,
        }, indent=2))
    elif args.command == "state":
        state = get_empathy_state()
        print(json.dumps({
            "frustration": state.frustration,
            "confidence": state.confidence,
            "curiosity": state.curiosity,
            "mood": state.mood,
            "tone": state.tone,
            "risk_appetite": state.risk_appetite,
            "sentiment_score": state.sentiment_score,
        }, indent=2))
    elif args.command == "history":
        print(json.dumps(adaptation_history(), indent=2, default=str))
    elif args.command == "reset":
        reset_adaptation()
        print("Adaptation history reset.")
    else:
        p.print_help()


if __name__ == "__main__":
    cli()