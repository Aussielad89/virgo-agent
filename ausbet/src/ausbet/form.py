"""Racing form: load runners from CSV/JSON and derive probability estimates.

The probability model is deliberately crude and transparent — a readable
heuristic (last-start position, recent form figures, career win ratio,
weight) that normalises to a full book (probabilities sum to 1.0). It is a
starting point for value scanning, NOT a replacement for real form analysis.

CSV schema (header row required):

    number,name,barrier,weight,form_figures,career_starts,career_wins,last_start,jockey,trainer,scratched
    1,Mighty Mo,3,58.5,231x45,12,3,5,J McDonald,C Waller,false

`form_figures` digits are finish positions, `x` = spell/not applicable.
`last_start` overrides the last digit of form_figures when both present.
`scratched` accepts true/1/yes (case-insensitive).
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from ausbet.value import ValuePick, scan_market

_TRUE = {"true", "1", "yes", "y"}


@dataclass
class FormRunner:
    """One horse/greyhound in a race."""

    number: int
    name: str
    barrier: int | None = None
    weight: float | None = None  # kg (Australia)
    form_figures: str = ""
    career_starts: int | None = None
    career_wins: int | None = None
    last_start: int | None = None  # last-start finish position; None = unraced
    jockey: str = ""
    trainer: str = ""
    scratched: bool = False

    @property
    def unraced(self) -> bool:
        return self.last_start is None

    @property
    def recent_finishes(self) -> list[int]:
        """Last up-to-3 finish positions parsed from form_figures."""
        digits = [int(d) for d in re.sub(r"[^0-9]", "", self.form_figures)]
        return digits[-3:]


def load_form_csv(path: str | Path) -> list[FormRunner]:
    runners: list[FormRunner] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            runners.append(_row_to_runner(row))
    if not runners:
        raise ValueError(f"no runners found in {path}")
    return runners


def load_form_json(path: str | Path) -> list[FormRunner]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    runners = []
    for r in data.get("runners", []):
        runners.append(_row_to_runner(r))
    if not runners:
        raise ValueError(f"no runners found in {path}")
    return runners


def load_form(path: str | Path) -> list[FormRunner]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        return load_form_json(path)
    return load_form_csv(path)


def _row_to_runner(r: dict) -> FormRunner:
    def _int(key: str) -> int | None:
        v = r.get(key, "")
        return int(v) if str(v).strip() not in ("", "None", "null") else None

    def _float(key: str) -> float | None:
        v = r.get(key, "")
        return float(v) if str(v).strip() not in ("", "None", "null") else None

    last = _int("last_start")
    figures = str(r.get("form_figures", "") or "")
    if last is None and figures:
        last = int(re.sub(r"[^0-9]", "", figures)[-1]) if re.sub(r"[^0-9]", "", figures) else None
    return FormRunner(
        number=_int("number") or 0,
        name=str(r.get("name", "")).strip(),
        barrier=_int("barrier"),
        weight=_float("weight"),
        form_figures=figures,
        career_starts=_int("career_starts"),
        career_wins=_int("career_wins"),
        last_start=last,
        jockey=str(r.get("jockey", "") or ""),
        trainer=str(r.get("trainer", "") or ""),
        scratched=str(r.get("scratched", "") or "").strip().lower() in _TRUE,
    )


def _score(runner: FormRunner, field_max_weight: float) -> float:
    """Crude transparent form score: higher = more likely to win."""
    s = 0.0
    if runner.last_start is not None:
        s += max(1.0, 10.0 - (runner.last_start - 1) * 1.0)  # 1st=10 ... 10th+=1
    else:
        s += 5.0  # unraced gets an average mark
    finishes = runner.recent_finishes
    if finishes:
        s += sum(max(0.0, 11.0 - f) for f in finishes) / 2.0  # recent form
    if runner.career_starts and runner.career_wins is not None:
        s += (runner.career_wins / runner.career_starts) * 5.0
    if runner.weight is not None and field_max_weight:
        s += (field_max_weight - runner.weight) * 0.2  # lighter carries score higher
    return max(0.0, s)


def form_probabilities(runners: list[FormRunner]) -> dict[str, float]:
    """Normalised win probabilities for all non-scratched runners.

    A +1.0 floor keeps unraced/struggling runners above zero probability so
    every runner stays in the book. Sum == 1.0.
    """
    active = [r for r in runners if not r.scratched]
    if not active:
        raise ValueError("no active runners (all scratched?)")
    max_w = max((r.weight for r in active if r.weight is not None), default=0.0)
    scores = {r.name: _score(r, max_w) + 1.0 for r in active}
    total = sum(scores.values())
    return {name: round(score / total, 4) for name, score in scores.items()}


def race_scan(
    runners: list[FormRunner],
    odds: list[tuple[str, str | float]] | None = None,
) -> tuple[dict[str, float], list[ValuePick]]:
    """Form probabilities + value scan against market odds.

    `odds` is [(selection_name, odds), ...] — runners without odds are shown
    in the probability table but skipped in the value scan.
    Returns (probabilities, picks).
    """
    probs = form_probabilities(runners)
    picks: list[ValuePick] = []
    if odds:
        names_with_odds = {name for name, _ in odds}
        picks = scan_market(
            [(n, o) for n, o in odds if n in probs],
            {n: p for n, p in probs.items() if n in names_with_odds},
        )
    return probs, picks
