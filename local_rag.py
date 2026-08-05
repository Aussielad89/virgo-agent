"""
local_rag — queryable knowledge layer over kb/ plus ad-hoc documents.

Wraps the existing ``_rag`` engine (TF-IDF with optional Ollama/cognee/
mem0 backends) behind a small, friendly API and adds a **virtual document**
registry: runtime text (pasted notes, runbook summaries, a project README,
the current goal) can be injected into the retrievable corpus without
touching the on-disk ``kb/`` tree.

Usage::

    from local_rag import LocalRag
    rag = LocalRag()
    rag.add_virtual("note-1", "Run this project with: python main.py --demo")
    rag.query("how do I run the demo?")   # merges kb/ hits + virtual docs
    rag.inject("how do I run the demo?")  # prompt-ready knowledge block

Stdlib-only (defensive import of _rag). Conventions: PascalCase classes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from _log import log

# Virtual documents live here so they survive restarts.
DEFAULT_VIRTUAL_PATH = Path(".virgo_memory") / "rag_virtual.json"

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{3,}")

# Sentinel: distinguishes "use the default engine" from an explicit
# ``kb_engine=None`` request to run without any kb/ backend.
_AUTO = object()


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _score(query_tokens: set[str], doc_tokens: set[str]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / len(query_tokens)  # recall-weighted


class LocalRag:
    """Friendly RAG facade: kb/ engine + persistent virtual documents."""

    def __init__(
        self,
        virtual_path: str | Path | None = None,
        kb_engine: Any = _AUTO,
    ) -> None:
        self.virtual_path = Path(virtual_path) if virtual_path else DEFAULT_VIRTUAL_PATH
        self._virtual: dict[str, str] = {}
        self._load_virtual()
        # Wrap the existing engine lazily; fall back to our keyword scorer.
        if kb_engine is _AUTO:
            try:
                import _rag

                kb_engine = _rag
            except Exception as exc:  # pragma: no cover
                log.warning("local_rag: _rag unavailable (%s)", exc)
                kb_engine = None
        self._engine = kb_engine

    # ── virtual documents ────────────────────────────────────────────
    def _load_virtual(self) -> None:
        if not self.virtual_path.exists():
            return
        try:
            data = json.loads(self.virtual_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("local_rag: corrupt virtual doc store: %s", exc)
            return
        self._virtual = data if isinstance(data, dict) else {}

    def _save_virtual(self) -> None:
        self.virtual_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.virtual_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._virtual, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.virtual_path)

    def add_virtual(self, name: str, text: str) -> None:
        """Add (or replace) a runtime document to the retrievable corpus."""
        self._virtual[name] = text
        self._save_virtual()

    def remove_virtual(self, name: str) -> bool:
        if name in self._virtual:
            del self._virtual[name]
            self._save_virtual()
            return True
        return False

    def virtual_docs(self) -> dict[str, str]:
        return dict(self._virtual)

    # ── querying ─────────────────────────────────────────────────────
    def query(self, query: str, k: int = 3) -> list[dict[str, str]]:
        """Return merged hits: kb/ passages first, then virtual docs.

        Each hit: {"source": str, "text": str}.
        """
        hits: list[dict[str, str]] = []
        # kb/ engine hits (defensive: whatever shape they come back in)
        if self._engine is not None:
            try:
                raw = self._engine.retrieve(query, top_k=k)
                for item in raw or []:
                    if isinstance(item, str):
                        hits.append({"source": "kb", "text": item})
                    elif isinstance(item, (tuple, list)) and len(item) >= 2:
                        hits.append({"source": str(item[0]), "text": str(item[1])})
            except Exception as exc:  # pragma: no cover
                log.debug("local_rag: kb query failed: %s", exc)
        # virtual docs by recall-weighted keyword scoring
        q_tokens = _tokens(query)
        scored = [
            (_score(q_tokens, _tokens(text)), name, text)
            for name, text in self._virtual.items()
        ]
        scored.sort(key=lambda t: t[0], reverse=True)
        for score, name, text in scored:
            if score > 0 and len(hits) < k + 2:
                hits.append({"source": f"note:{name}", "text": text[:700]})
        return hits[: k + 2]

    def inject(self, query: str, k: int = 3) -> str:
        """Prompt-ready knowledge block, or '' when nothing matches."""
        hits = self.query(query, k=k)
        if not hits:
            return ""
        block = "\n\n".join(f"[from {h['source']}]\n{h['text']}" for h in hits)
        return (
            "=== KNOWLEDGE BASE (retrieved; ground answers here when relevant) ===\n"
            f"{block}\n"
            "=== END KNOWLEDGE BASE ==="
        )

    def status(self) -> dict[str, Any]:
        """Combined status: engine backend + doc counts."""
        engine_status: dict[str, Any] = {}
        if self._engine is not None:
            try:
                engine_status = self._engine.kb_status() or {}
            except Exception:  # pragma: no cover
                engine_status = {}
        engine_status["virtual_docs"] = len(self._virtual)
        engine_status["total_docs"] = (
            int(engine_status.get("doc_count", 0) or 0) + len(self._virtual)
        )
        return engine_status


# ── module-level convenience ───────────────────────────────────────────

_INSTANCE: LocalRag | None = None


def get_rag() -> LocalRag:
    """Lazy process-wide LocalRag singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = LocalRag()
    return _INSTANCE
