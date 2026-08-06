"""
virgo_dna_fingerprint — Codebase DNA fingerprint visualization.

Extends virgo_flavor.py's style profiling into a visual
fingerprint that can be compared across projects or tracked
over time. Renders as a radial chart showing the codebase's
stylistic signature.
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

FINGERPRINT_DIR = HERE / ".virgo_fingerprints"
FINGERPRINT_DIR.mkdir(exist_ok=True)
FINGERPRINT_HISTORY = FINGERPRINT_DIR / "history.json"


@dataclass
class FingerprintVector:
    dimensions: dict[str, float] = field(default_factory=dict)
    dominant: str = "minimalist"
    files_scanned: int = 0
    timestamp: str = ""
    project_name: str = ""


def _load_flavor() -> dict[str, Any]:
    flavor_file = HERE / ".virgo_flavor.json"
    if flavor_file.exists():
        try:
            return json.loads(flavor_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def compute_fingerprint(project_name: str = "") -> FingerprintVector:
    flavor = _load_flavor()
    vector = flavor.get("vector", {})
    dominant = flavor.get("dominant_flavor", "minimalist")
    files_scanned = flavor.get("files_scanned", 0)

    # Normalize to a fixed set of dimensions for comparison
    all_dims = [
        "functional", "oop", "minimalist", "enterprise",
        "prototype", "async", "type_heavy", "test_driven",
        "data_heavy", "web", "cli", "scripting",
    ]
    normalized = {}
    total = sum(vector.values()) or 1.0
    for dim in all_dims:
        normalized[dim] = round(vector.get(dim, 0.0) / total, 4)

    fp = FingerprintVector(
        dimensions=normalized,
        dominant=dominant,
        files_scanned=files_scanned,
        timestamp=__import__("datetime").datetime.now().isoformat(),
        project_name=project_name or HERE.name,
    )
    return fp


def fingerprint_to_radial(fp: FingerprintVector) -> list[dict[str, Any]]:
    """Convert fingerprint to radial chart data points."""
    dims = fp.dimensions
    keys = sorted(dims.keys())
    n = len(keys)
    points = []
    for i, key in enumerate(keys):
        angle = (2 * math.pi * i) / n - math.pi / 2
        value = dims.get(key, 0.0)
        points.append({
            "dimension": key,
            "value": value,
            "angle_rad": round(angle, 4),
            "x": round(math.cos(angle) * value, 4),
            "y": round(math.sin(angle) * value, 4),
        })
    return points


def fingerprint_to_barcode(fp: FingerprintVector) -> str:
    """Convert fingerprint to a barcode-like string representation."""
    dims = fp.dimensions
    keys = sorted(dims.keys())
    barcode = ""
    for key in keys:
        val = int(dims.get(key, 0.0) * 10)
        barcode += key[:3].upper() + ":" + "█" * val + "░" * (10 - val) + " "
    return barcode.strip()


def save_fingerprint(fp: FingerprintVector) -> None:
    try:
        history = load_history()
        entry = {
            "project_name": fp.project_name,
            "dominant": fp.dominant,
            "files_scanned": fp.files_scanned,
            "timestamp": fp.timestamp,
            "vector": fp.dimensions,
        }
        history.append(entry)
        history = history[-50:]
        FINGERPRINT_HISTORY.write_text(
            json.dumps(history, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        log.error("fingerprint save failed: %s", exc)


def load_history() -> list[dict[str, Any]]:
    if not FINGERPRINT_HISTORY.exists():
        return []
    try:
        return json.loads(FINGERPRINT_HISTORY.read_text(encoding="utf-8"))
    except Exception:
        return []


def compare_fingerprints(fp1: FingerprintVector, fp2: FingerprintVector) -> dict[str, Any]:
    """Compare two fingerprints using cosine similarity."""
    keys = sorted(set(fp1.dimensions.keys()) | set(fp2.dimensions.keys()))
    v1 = [fp1.dimensions.get(k, 0.0) for k in keys]
    v2 = [fp2.dimensions.get(k, 0.0) for k in keys]

    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(a * a for a in v2))

    similarity = dot / (mag1 * mag2) if (mag1 * mag2) > 0 else 0.0

    differences = {}
    for k in keys:
        diff = abs(fp1.dimensions.get(k, 0.0) - fp2.dimensions.get(k, 0.0))
        if diff > 0.01:
            differences[k] = round(diff, 4)

    return {
        "similarity": round(similarity, 4),
        "genetic_distance": round(1.0 - similarity, 4),
        "differences": differences,
        "fp1_project": fp1.project_name,
        "fp2_project": fp2.project_name,
    }


def track_fingerprint(project_name: str = "") -> dict[str, Any]:
    """Compute and save a fingerprint, returning the result."""
    fp = compute_fingerprint(project_name)
    save_fingerprint(fp)
    return {
        "fingerprint": {
            "project_name": fp.project_name,
            "dominant": fp.dominant,
            "files_scanned": fp.files_scanned,
            "timestamp": fp.timestamp,
        },
        "radial_points": fingerprint_to_radial(fp),
        "barcode": fingerprint_to_barcode(fp),
    }


def cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Virgo DNA Fingerprint")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("fingerprint", help="Compute current fingerprint")
    sub.add_parser("barcode", help="Show barcode representation")
    sub.add_parser("history", help="Show fingerprint history")
    compare = sub.add_parser("compare")
    compare.add_argument("project", help="Project name to compare against")
    args = p.parse_args()
    if args.command == "fingerprint":
        result = track_fingerprint()
        print(json.dumps(result, indent=2, default=str))
    elif args.command == "barcode":
        fp = compute_fingerprint()
        print(fingerprint_to_barcode(fp))
    elif args.command == "history":
        print(json.dumps(load_history(), indent=2, default=str))
    elif args.command == "compare":
        fp1 = compute_fingerprint()
        fp2 = FingerprintVector(
            dimensions={},
            dominant="",
            project_name=args.project,
        )
        # Load matching history entry
        for entry in load_history():
            if entry.get("project_name") == args.project:
                fp2 = FingerprintVector(
                    dimensions=entry.get("vector", {}),
                    dominant=entry.get("dominant", ""),
                    project_name=args.project,
                )
                break
        result = compare_fingerprints(fp1, fp2)
        print(json.dumps(result, indent=2))
    else:
        p.print_help()


if __name__ == "__main__":
    cli()