"""
runbook — distill repeated agent failures into human-readable runbooks.

When the same kind of task fails more than once, Virgo writes a Markdown
runbook into ``kb/runbooks/`` documenting the failure cluster: what went
wrong, how often, and the workarounds its past self learned. The next time
the agent faces a similar goal, the experience memory surfaces those
lessons in the prompt.

Clustering is keyword-based (Jaccard over extracted tokens), so it works
with zero dependencies and no LLM.

Stdlib-only. Conventions: PascalCase classes, ``from _log import log``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _log import log

DEFAULT_KB_DIR = Path("kb")
RUNBOOKS_DIR = "runbooks"

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{4,}")
_STOPWORDS = frozenset(
    {
        "this", "that", "with", "from", "have", "will", "your", "what",
        "when", "were", "been", "they", "them", "their", "then", "than",
        "here", "there", "would", "could", "should", "which", "while",
        "about", "after", "before", "being", "where", "these", "those",
        "some", "such", "into", "over", "also", "because", "other",
        "more", "most", "very", "just", "like", "goal", "task", "failed",
        "error", "virgo", "agent",
    }
)


def _keywords(text: str) -> set[str]:
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "runbook"


class RunbookGenerator:
    """Scan memory for failure clusters and emit Markdown runbooks."""

    def __init__(
        self,
        kb_dir: str | Path | None = None,
        memory: Any = None,
    ) -> None:
        self.kb_dir = Path(kb_dir) if kb_dir else DEFAULT_KB_DIR
        self.runbooks_dir = self.kb_dir / RUNBOOKS_DIR
        if memory is None:
            try:
                from memory_store import get_unified

                memory = get_unified()
            except Exception as exc:  # pragma: no cover
                log.warning("runbook: unified memory unavailable (%s)", exc)
                memory = None
        self.memory = memory

    # ── failure collection ────────────────────────────────────────────
    def _failure_entries(self) -> list[dict[str, Any]]:
        """Gather failed entries from every writable backend."""
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        if self.memory is not None:
            if self.memory.experience is not None:
                try:
                    raw = self.memory.experience._entries
                    for e in raw:
                        if not e.get("success"):
                            entries.append(e)
                            seen.add(str(e.get("id")))
                except Exception:  # pragma: no cover
                    pass
            if self.memory.learning is not None:
                try:
                    raw = self.memory.learning.list(limit=500)
                    for e in raw or []:
                        if not e.get("success") and str(e.get("id")) not in seen:
                            entries.append(e)
                except Exception:  # pragma: no cover
                    pass
        return entries

    # ── clustering ────────────────────────────────────────────────────
    def _cluster(self, entries: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Greedy clustering by pairwise keyword overlap (>= 0.18)."""
        clusters: list[list[dict[str, Any]]] = []
        for entry in entries:
            kw = _keywords(f"{entry.get('goal', '')} {entry.get('approach', '')}")
            placed = False
            for cluster in clusters:
                rep_kw = _keywords(f"{cluster[0].get('goal', '')} {cluster[0].get('approach', '')}")
                if _overlap(kw, rep_kw) >= 0.18:
                    cluster.append(entry)
                    placed = True
                    break
            if not placed:
                clusters.append([entry])
        return [c for c in clusters if len(c) >= 2]  # only repeated failures

    # ── output ────────────────────────────────────────────────────────
    def generate(
        self,
        min_failures: int = 2,
        limit: int = 5,
    ) -> list[Path]:
        """Write runbooks for failure clusters with >= *min_failures* hits.

        Returns the list of Markdown files written.
        """
        entries = self._failure_entries()
        clusters = self._cluster(entries)
        written: list[Path] = []
        for cluster in clusters[:limit]:
            if len(cluster) < min_failures:
                continue
            path = self._write_runbook(cluster)
            if path is not None:
                written.append(path)
        log.info("runbook: wrote %d runbook(s) from %d failure(s)",
                 len(written), len(entries))
        return written

    def _write_runbook(self, cluster: list[dict[str, Any]]) -> Path | None:
        goals = [str(e.get("goal", "")).strip() for e in cluster if e.get("goal")]
        lessons = [
            str(e.get("lesson", "")).strip()
            for e in cluster
            if e.get("lesson")
        ]
        outcomes = [str(e.get("outcome", "")).strip() for e in cluster if e.get("outcome")]
        title = goals[0][:80] if goals else "Repeated agent failure"
        slug = _slug(title)
        self.runbooks_dir.mkdir(parents=True, exist_ok=True)
        path = self.runbooks_dir / f"{slug}.md"

        body = [
            f"# Runbook: {title}",
            "",
            f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} "
            f"- {len(cluster)} recorded failure(s).",
            "",
            "## Symptoms",
            "",
        ]
        for g in goals[:8]:
            body.append(f"- {g}")
        if outcomes:
            body += ["", "## Observed outcomes", ""]
            for o in outcomes[:8]:
                body.append(f"- {o}")
        if lessons:
            body += ["", "## Workarounds learned", ""]
            for l in lessons[:10]:
                body.append(f"- {l}")
        body += [
            "",
            "## How to use",
            "",
            "These lessons are auto-injected into future agent prompts when a",
            "goal overlaps with this runbook's keywords, so the agent stops",
            "repeating the same failure.",
            "",
        ]
        path.write_text("\n".join(body), encoding="utf-8")
        log.info("runbook: wrote %s", path)
        return path

    def list_runbooks(self) -> list[Path]:
        """Return existing runbook files (newest first)."""
        if not self.runbooks_dir.exists():
            return []
        return sorted(self.runbooks_dir.glob("*.md"), reverse=True)


# ── module-level convenience ───────────────────────────────────────────

_INSTANCE: RunbookGenerator | None = None


def get_runbooks(kb_dir: str | Path | None = None) -> RunbookGenerator:
    """Lazy process-wide RunbookGenerator singleton."""
    global _INSTANCE
    if kb_dir is not None:
        _INSTANCE = RunbookGenerator(kb_dir)
    elif _INSTANCE is None:
        _INSTANCE = RunbookGenerator()
    return _INSTANCE
