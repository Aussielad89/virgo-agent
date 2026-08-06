"""
virgo_dream_viz — Dream journal visualizer for Virgo Desktop.

Renders the agent's idle dream journal as an evolving
constellation or mind map. Each dream becomes a node,
and semantic connections between dreams become edges.
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

DREAM_VIZ_DIR = HERE / ".virgo_dream_viz"
DREAM_VIZ_DIR.mkdir(exist_ok=True)


@dataclass
class DreamNode:
    id: str
    text: str
    category: str = "reflection"
    timestamp: str = ""
    weight: float = 1.0
    x: float = 0.0
    y: float = 0.0


@dataclass
class DreamEdge:
    source: str
    target: str
    similarity: float = 0.0


def _load_dreams() -> dict[str, Any]:
    dreams_file = HERE / ".virgo_dreams" / "index.json"
    if dreams_file.exists():
        try:
            return json.loads(dreams_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"dreams": [], "insights": []}


def _keyword_overlap(text1: str, text2: str) -> float:
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection = words1 & words2
    return len(intersection) / min(len(words1), len(words2))


def build_constellation() -> dict[str, Any]:
    data = _load_dreams()
    dreams = data.get("dreams", [])
    insights = data.get("insights", [])

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Create nodes from dreams
    for i, dream in enumerate(dreams):
        text = " ".join(dream.get("dreams", []))
        insights_text = " ".join(dream.get("insights", []))
        combined = f"{text} {insights_text}"

        # Categorize
        category = "reflection"
        if any(w in combined.lower() for w in ["bug", "error", "fail", "fix", "broken"]):
            category = "debug"
        elif any(w in combined.lower() for w in ["refactor", "split", "clean", "improve"]):
            category = "refactor"
        elif any(w in combined.lower() for w in ["test", "pass", "green", "coverage"]):
            category = "testing"
        elif any(w in combined.lower() for w in ["architect", "design", "pattern", "structure"]):
            category = "architecture"

        angle = (2 * math.pi * i) / max(len(dreams), 1)
        radius = 1.0 + (i % 3) * 0.3

        nodes.append({
            "id": f"dream_{i}",
            "text": text[:100],
            "category": category,
            "timestamp": dream.get("timestamp", ""),
            "weight": len(text),
            "x": round(math.cos(angle) * radius, 4),
            "y": round(math.sin(angle) * radius, 4),
        })

    # Create edges based on semantic similarity
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            sim = _keyword_overlap(
                nodes[i]["text"],
                nodes[j]["text"],
            )
            if sim > 0.1:
                edges.append({
                    "source": nodes[i]["id"],
                    "target": nodes[j]["id"],
                    "similarity": round(sim, 4),
                })

    # Add insight nodes
    insight_offset = len(nodes)
    for i, insight in enumerate(insights[:10]):
        if isinstance(insight, dict):
            text = insight.get("text", str(insight))
        else:
            text = str(insight)
        angle = (2 * math.pi * (insight_offset + i)) / max(len(insights), 1)
        nodes.append({
            "id": f"insight_{i}",
            "text": text[:100],
            "category": "insight",
            "timestamp": "",
            "weight": len(text),
            "x": round(math.cos(angle) * 0.7, 4),
            "y": round(math.sin(angle) * 0.7, 4),
        })

    return {
        "nodes": nodes,
        "edges": edges,
        "dream_count": len(dreams),
        "insight_count": len(insights),
        "generated": __import__("datetime").datetime.now().isoformat(),
    }


def render_ascii(constellation: dict[str, Any]) -> str:
    """Render constellation as ASCII art."""
    nodes = constellation.get("nodes", [])
    edges = constellation.get("edges", [])

    if not nodes:
        return "(no dreams to visualize)"

    # Simple 40x20 grid
    width = 40
    height = 20
    grid = [[" " for _ in range(width)] for _ in range(height)]

    # Map nodes to grid positions
    for node in nodes:
        x = int((node["x"] + 1.5) / 3.0 * (width - 1))
        y = int((node["y"] + 1.5) / 3.0 * (height - 1))
        x = max(0, min(width - 1, x))
        y = max(0, min(height - 1, y))
        cat = node.get("category", "reflection")
        symbol = {
            "reflection": "o",
            "debug": "x",
            "refactor": "r",
            "testing": "t",
            "architecture": "a",
            "insight": "*",
        }.get(cat, "o")
        grid[y][x] = symbol

    # Draw edges
    for edge in edges:
        src = next((n for n in nodes if n["id"] == edge["source"]), None)
        tgt = next((n for n in nodes if n["id"] == edge["target"]), None)
        if src and tgt:
            x1 = int((src["x"] + 1.5) / 3.0 * (width - 1))
            y1 = int((src["y"] + 1.5) / 3.0 * (height - 1))
            x2 = int((tgt["x"] + 1.5) / 3.0 * (width - 1))
            y2 = int((tgt["y"] + 1.5) / 3.0 * (height - 1))
            # Simple line drawing
            steps = max(abs(x2 - x1), abs(y2 - y1), 1)
            for s in range(steps + 1):
                t = s / steps
                x = int(x1 + (x2 - x1) * t)
                y = int(y1 + (y2 - y1) * t)
                if 0 <= x < width and 0 <= y < height:
                    if grid[y][x] == " ":
                        grid[y][x] = "."

    return "\n".join("".join(row) for row in grid)


def get_dream_timeline() -> list[dict[str, Any]]:
    """Return dreams sorted by timestamp for timeline scrubbing."""
    data = _load_dreams()
    dreams = data.get("dreams", [])
    return sorted(dreams, key=lambda d: d.get("timestamp", ""), reverse=True)


def get_category_stats() -> dict[str, int]:
    """Count dreams by category."""
    constellation = build_constellation()
    stats: dict[str, int] = {}
    for node in constellation.get("nodes", []):
        cat = node.get("category", "reflection")
        stats[cat] = stats.get(cat, 0) + 1
    return stats


def cli() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Virgo Dream Visualizer")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("constellation", help="Build dream constellation")
    sub.add_parser("ascii", help="Render ASCII constellation")
    sub.add_parser("timeline", help="Show dream timeline")
    sub.add_parser("stats", help="Show category statistics")
    args = p.parse_args()
    if args.command == "constellation":
        result = build_constellation()
        print(json.dumps(result, indent=2, default=str))
    elif args.command == "ascii":
        result = build_constellation()
        print(render_ascii(result))
    elif args.command == "timeline":
        timeline = get_dream_timeline()
        for d in timeline[:10]:
            ts = d.get("timestamp", "")
            dreams = d.get("dreams", [])
            print(f"[{ts}] {len(dreams)} dreams")
    elif args.command == "stats":
        stats = get_category_stats()
        for cat, count in sorted(stats.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count}")
    else:
        p.print_help()


if __name__ == "__main__":
    cli()