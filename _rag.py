"""_rag.py — tiny CPU-only RAG layer for Virgo chat.

No external dependencies (pure stdlib). On every chat turn we load the
knowledge base from ``kb/`` (markdown / txt / json), build a TF-IDF index
over chunked documents, and return the ``top_k`` most relevant passages for
the user's message. The caller injects those passages into the system
prompt so the local LLM can ground its reply in *your* data.

Design notes
------------
* Documents are split into ~700-char overlapping chunks so retrieval stays
  granular without blowing up the context window.
* TF-IDF + cosine similarity, computed with ``math`` only. For a few
  hundred KB chunks this is sub-millisecond on a CPU — no GPU needed.
* The index is rebuilt lazily and cached in-memory per process. Editing a
  file in ``kb/`` triggers a rebuild on the next turn (mtime check).
* If ``kb/`` is empty or missing, retrieval returns ``""`` and chat is
  unaffected (graceful degradation).

Drop your own ``.md`` / ``.txt`` / ``.json`` files into ``kb/`` (or
``kb/private/`` which is gitignored) to teach Virgo about your projects.
"""

from __future__ import annotations

import math
import re
import threading
from pathlib import Path

# Knowledge base lives next to this file (agent-framework/kb/).
KB_DIR = Path(__file__).resolve().parent / "kb"
PRIVATE_DIR = KB_DIR / "private"

_CHUNK_SIZE = 700
_CHUNK_OVERLAP = 120
_MAX_CONTEXT_CHARS = 2600  # hard cap so we never blow the model context

_lock = threading.RLock()  # reentrant: _get_index() is called while holding the lock
_cache: dict | None = None  # {"mtime": float, "chunks": list, "idf": dict, "vocab": set}


# --------------------------------------------------------------------------
# Indexing
# --------------------------------------------------------------------------
def _iter_documents() -> list[Path]:
    docs: list[Path] = []
    for d in (KB_DIR, PRIVATE_DIR):
        if not d.exists():
            continue
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() in (".md", ".txt", ".json"):
                docs.append(p)
    return docs


def _chunk_text(text: str) -> list[str]:
    """Split into overlapping chunks, dropping whitespace-only fragments."""
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    chunks: list[str] = []
    step = max(1, _CHUNK_SIZE - _CHUNK_OVERLAP)
    for i in range(0, len(text), step):
        piece = text[i : i + _CHUNK_SIZE]
        if len(piece) >= 40:  # ignore tiny tail fragments
            chunks.append(piece)
    return chunks


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _newest_mtime() -> float:
    m = 0.0
    for p in _iter_documents():
        try:
            m = max(m, p.stat().st_mtime)
        except OSError:
            pass
    return m


def _build_index() -> dict:
    """Build (or rebuild) the TF-IDF index over the KB."""
    chunks: list[tuple[str, str]] = []  # (doc_name, text)
    for p in _iter_documents():
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for c in _chunk_text(raw):
            chunks.append((p.name, c))

    if not chunks:
        return {"mtime": _newest_mtime(), "chunks": [], "idf": {}, "vocab": set()}

    # term frequency per chunk
    tf: list[dict[str, int]] = []
    vocab: set[str] = set()
    for _, text in chunks:
        counts: dict[str, int] = {}
        for tok in _tokenize(text):
            counts[tok] = counts.get(tok, 0) + 1
            vocab.add(tok)
        tf.append(counts)

    n = len(chunks)
    idf: dict[str, float] = {}
    for tok in vocab:
        df = sum(1 for c in tf if tok in c)
        idf[tok] = math.log((n + 1) / (df + 1)) + 1.0

    return {"mtime": _newest_mtime(), "chunks": chunks, "idf": idf, "vocab": vocab, "tf": tf}


def _get_index() -> dict:
    global _cache
    with _lock:
        if _cache is None or _cache.get("mtime", -1) != _newest_mtime():
            _cache = _build_index()
        return _cache


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------
def _vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    vec: dict[str, float] = {}
    for t in tokens:
        if t in idf:
            vec[t] = vec.get(t, 0.0) + idf[t]
    # L2 normalise
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm > 0:
        for k in vec:
            vec[k] /= norm
    return vec


def retrieve(query: str, top_k: int = 3) -> list[str]:
    """Return the ``top_k`` most relevant KB passages for ``query``.

    Returns an empty list when the KB is empty. Each item is a short
    passage (≤~700 chars) tagged with its source filename.
    """
    idx = _get_index()
    chunks = idx["chunks"]
    if not chunks:
        return []

    qvec = _vector(_tokenize(query), idx["idf"])
    if not qvec:
        return []

    scored: list[tuple[float, int]] = []
    for i, counts in enumerate(idx["tf"]):
        dvec = _vector(list(counts.keys()), idx["idf"])
        # cosine similarity
        dot = sum(qvec[t] * dvec.get(t, 0.0) for t in qvec)
        if dot > 0:
            scored.append((dot, i))

    scored.sort(reverse=True)
    out: list[str] = []
    total = 0
    for _, i in scored[:top_k]:
        name, text = chunks[i]
        passage = f"[from {name}]\n{text}"
        if total + len(passage) > _MAX_CONTEXT_CHARS:
            # trim to fit budget
            room = _MAX_CONTEXT_CHARS - total
            if room < 120:
                break
            passage = passage[:room]
        out.append(passage)
        total += len(passage)
        if total >= _MAX_CONTEXT_CHARS:
            break
    return out


def kb_context(query: str, top_k: int = 3) -> str:
    """Human-readable context block to prepend to the system prompt.

    Returns ``""`` when nothing relevant is found (chat unaffected).
    """
    hits = retrieve(query, top_k=top_k)
    if not hits:
        return ""
    block = "\n\n".join(hits)
    return (
        "=== KNOWLEDGE BASE (retrieved, ground your answer in this when relevant) ===\n"
        f"{block}\n"
        "=== END KNOWLEDGE BASE ==="
    )


def kb_status() -> dict:
    """Return a small status dict for UI / CLI display."""
    docs = _iter_documents()
    idx = _get_index()
    return {
        "kb_dir": str(KB_DIR),
        "doc_count": len(docs),
        "chunk_count": len(idx.get("chunks", [])),
        "ready": len(docs) > 0,
    }


if __name__ == "__main__":
    # Simple self-test / demo
    s = kb_status()
    print(f"KB ready={s['ready']} docs={s['doc_count']} chunks={s['chunk_count']}")
    q = "what are the best research websites"
    hits = retrieve(q, top_k=3)
    if hits:
        print(f"\nTop {len(hits)} hits for: {q!r}\n")
        for h in hits:
            print("-" * 60)
            print(h[:400])
    else:
        print("No KB documents found — drop .md/.txt/.json files into kb/")
