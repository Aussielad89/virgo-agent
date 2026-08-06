"""
virgo_empathy — agent empathy layer.

Reads repo mood from commit sentiment, issue language, and recent PR
feedback to calibrate tone and risk appetite before proposing changes.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from _log import log

HERE = Path(__file__).parent
EMPATHY_FILE = HERE / ".virgo_empathy.json"

_POSITIVE = re.compile(r"\b(good|great|awesome|nice|love|excellent|perfect|thanks|fixed|solved|clean|beautiful)\b", re.I)
_NEGATIVE = re.compile(r"\b(bad|terrible|awful|hate|broken|bug|fail|error|hotfix|urgent|critical|wtf|damn|fragile|spaghetti)\b", re.I)
_STRESS = re.compile(r"\b(deadline|hotfix|urgent|production|outage|rollback|revert|emergency|blocker)\b", re.I)


def _git(args: list[str], cwd: Path | None = None) -> str | None:
    cwd = cwd or HERE
    try:
        r = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _recent_commits(n: int = 20) -> list[str]:
    out = _git(["log", f"-n{n}", "--pretty=format:%s"])
    return out.splitlines() if out else []


def _recent_messages(n: int = 50) -> list[str]:
    msgs = _recent_commits(n * 2)
    return msgs


def analyze_repo_mood(since_hours: int = 48) -> dict[str, Any]:
    commits = _recent_commits(30)
    messages = " ".join(commits)
    pos = len(_POSITIVE.findall(messages))
    neg = len(_NEGATIVE.findall(messages))
    stress = len(_STRESS.findall(messages))
    total = max(pos + neg, 1)
    score = round((pos - neg) / total, 4)
    if stress >= 3 or score < -0.3:
        mood = "stressed"
        tone = "cautious"
        risk = "high"
        suggestion = "Propose smaller, safer patches. Avoid risky refactors."
    elif score >= 0.4:
        mood = "happy"
        tone = "playful"
        risk = "low"
        suggestion = "Good time for bold improvements or cleanup."
    elif score <= -0.2:
        mood = "frustrated"
        tone = "empathetic"
        risk = "medium"
        suggestion = "Acknowledge pain points. Prefer minimal, targeted fixes."
    else:
        mood = "neutral"
        tone = "neutral"
        risk = "medium"
        suggestion = "Standard workflow. No special calibration needed."
    result = {
        "mood": mood,
        "tone": tone,
        "risk_appetite": risk,
        "sentiment_score": score,
        "positive_signals": pos,
        "negative_signals": neg,
        "stress_signals": stress,
        "suggestion": suggestion,
        "commit_count": len(commits),
        "since_hours": since_hours,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        EMPATHY_FILE.write_text(json.dumps(result, indent=2, default=str))
    except Exception:
        pass
    log.info("empathy: mood=%s tone=%s risk=%s", mood, tone, risk)
    return result


def get_empathy() -> dict[str, Any]:
    if EMPATHY_FILE.exists():
        try:
            return json.loads(EMPATHY_FILE.read_text())
        except Exception:
            pass
    return analyze_repo_mood()


def calibrate_prompt(prompt: str) -> str:
    e = get_empathy()
    prefix = {
        "cautious": "[CAUTION] This repo shows stress signals. Keep changes minimal and reversible.\n",
        "empathetic": "[EMPATHY] Recent commits suggest frustration. Acknowledge issues before proposing fixes.\n",
        "playful": "[EXPERIMENTAL] The repo is in a good mood. Bold ideas welcome.\n",
    }.get(e.get("tone", "neutral"), "")
    return prefix + prompt


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Virgo Empathy Layer")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--prompt", help="Calibrate a prompt string")
    args = p.parse_args()
    if args.refresh:
        res = analyze_repo_mood()
        print(json.dumps(res, indent=2, default=str))
    elif args.prompt:
        print(calibrate_prompt(args.prompt))
    else:
        print(json.dumps(get_empathy(), indent=2, default=str))


if __name__ == "__main__":
    cli()
