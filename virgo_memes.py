"""
virgo_memes — pipeline outcome meme generation.

Auto-generate ASCII-art memes based on pipeline outcomes.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime
from typing import Any

from _log import log

_SUCCESS_MEMES = [
    ("Drake", "Drake Format\n\n👎 Writing tests first\n👍 Generating passing code"),
    ("Doge", "        such code\n          very stable\n    many tests\n           wow"),
    ("Butterfly", "   caterpillar (tests fail)\n        ===p*===>\n   butterfly (green CI)"),
    ("Linux", "  compile  link  test  deploy\n  SUCCESS! All phases passed."),
]

_FAIL_MEMES = [
    ("This is Fine", "  This is fine.\n  🔥 🔥 🔥\n  Everything is fine."),
    ("Error Cat", "   /\\_/\\  \n  ( o.o ) \n   > ^ <  \n  [ERROR]"),
    ("Wait a minute", "👾 UNEXPECTED ERROR\n\nWait a minute...\nWho wrote this?\n*opens git blame*"),
]

_IDLE_MEMES = [
    ("Cat", "  |\\__/,|   (`\\\n  |o o  |__ _) )\n  (a    )__`  }\n   \"--'  ,  /'\n       |___|"),
    ("Snail", "  @..@\n (----)\n( >__< )\n ^^  ^^  slow and steady"),
]


def generate_meme(outcome: str) -> dict[str, Any]:
    outcome = (outcome or "idle").lower()
    if "success" in outcome or "pass" in outcome or "done" in outcome:
        title, art = random.choice(_SUCCESS_MEMES)
    elif "fail" in outcome or "error" in outcome or "critical" in outcome:
        title, art = random.choice(_FAIL_MEMES)
    else:
        title, art = random.choice(_IDLE_MEMES)
    result = {"title": title, "art": art, "outcome": outcome, "timestamp": datetime.now().isoformat() if sys.version_info >= (3, 7) else ""}
    log.info("meme: generated %s for %s", title, outcome)
    return result


def cli() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Virgo Pipeline Meme Generator")
    p.add_argument("outcome", nargs="?", default="idle")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    meme = generate_meme(args.outcome)
    if args.json:
        print(json.dumps(meme, indent=2, default=str))
    else:
        print(meme["art"])


if __name__ == "__main__":
    cli()
