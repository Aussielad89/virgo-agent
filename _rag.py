"""_rag.py — CPU-only RAG layer for Virgo chat.

No external dependencies for the default path (pure stdlib TF-IDF). On every
chat turn we load the knowledge base from ``kb/`` (markdown / txt / json),
build an index over chunked documents, and return the ``top_k`` most relevant
passages for the user's message. The caller injects those passages into the
system prompt so the local LLM can ground its reply in *your* data.

Backends
--------
``VIRGO_RAG_BACKEND`` selects the retrieval engine:

* ``tfidf``  — keyword TF-IDF + cosine (default, zero deps, always works).
* ``ollama`` — semantic embeddings via a local Ollama embedder
  (``nomic-embed-text`` by default). No API keys, runs on CPU.
* ``cognee``— optional graph-backed store (requires the ``cognee`` package;
  see cognee note below). This is the heavy/optional path.
* ``auto``    — (default when the env var is unset) try ``ollama`` first,
  fall back to ``tfidf`` on any failure (missing model, Ollama down, etc.).

Design notes
------------
* Documents are split into ~700-char overlapping chunks so retrieval stays
  granular without blowing up the context window.
* TF-IDF + cosine similarity, computed with ``math`` only. For a few
  hundred KB chunks this is sub-millisecond on a CPU — no GPU needed.
* The Ollama backend embeds each chunk once and caches the vectors
  in-memory, rebuilding when a ``kb/`` file changes (mtime check).
* The index is rebuilt lazily and cached in-memory per process. Editing a
  file in ``kb/`` triggers a rebuild on the next turn (mtime check).
* If ``kb/`` is empty or missing, retrieval returns ``""`` and chat is
  unaffected (graceful degradation).

COGNEE NOTE
    cognee's graph build (``cognify``) needs the LLM over the OpenAI
    ``/v1/chat/completions`` route. The local Ollama build here only serves
    ``/api/generate``, so full cognee graph builds can't complete. The
    ``cognee`` backend therefore uses cognee's pure vector retrieval
    (``SearchType.CHUNKS``) which only needs the embedder — proving the
    memory layer without requiring the graph-LLM step. cognee is an OPTIONAL
    dependency: importing ``_rag`` never requires it.

Drop your own ``.md`` / ``.txt`` / ``.json`` files into ``kb/`` (or
``kb/private/`` which is gitignored) to teach Virgo about your projects.
"""

from __future__ import annotations

import math
import os
import re
import threading
from pathlib import Path
from typing import Callable

# Knowledge base lives next to this file (agent-framework/kb/).
KB_DIR = Path(__file__).resolve().parent / "kb"
PRIVATE_DIR = KB_DIR / "private"

_CHUNK_SIZE = 700
_CHUNK_OVERLAP = 120
_MAX_CONTEXT_CHARS = 2600  # hard cap so we never blow the model context

# ── Backend selection ────────────────────────────────────────────────
# "auto" tries ollama, falls back to tfidf. Explicit values force a backend.
_RAG_BACKEND = os.environ.get("VIRGO_RAG_BACKEND", "auto").strip().lower()
if _RAG_BACKEND not in ("auto", "tfidf", "ollama", "cognee"):
    _RAG_BACKEND = "auto"

_lock = threading.RLock()  # reentrant: _get_index() is called while holding the lock
_cache: dict | None = None  # {"mtime": float, "chunks": list, "idf": dict, "vocab": set}
_vec_cache: dict | None = None  # {"mtime": float, "chunks": list, "vectors": list[list[float]]}


# --------------------------------------------------------------------------
# Shared document loading + chunking
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


def _all_chunks() -> list[tuple[str, str]]:
    """Return [(doc_name, text), ...] for every chunk in the KB."""
    chunks: list[tuple[str, str]] = []
    for p in _iter_documents():
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for c in _chunk_text(raw):
            chunks.append((p.name, c))
    return chunks


# --------------------------------------------------------------------------
# TF-IDF backend (zero deps, always available)
# --------------------------------------------------------------------------
def _tfidf_build() -> dict:
    """Build (or rebuild) the TF-IDF index over the KB."""
    chunks = _all_chunks()
    if not chunks:
        return {"mtime": _newest_mtime(), "chunks": [], "idf": {}, "vocab": set()}

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


def _tfidf_index() -> dict:
    global _cache
    with _lock:
        if _cache is None or _cache.get("mtime", -1) != _newest_mtime():
            _cache = _tfidf_build()
        return _cache


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


def _tfidf_retrieve(query: str, top_k: int) -> list[tuple[str, str]]:
    idx = _tfidf_index()
    chunks = idx["chunks"]
    if not chunks:
        return []
    qvec = _vector(_tokenize(query), idx["idf"])
    if not qvec:
        return []
    scored: list[tuple[float, int]] = []
    for i, counts in enumerate(idx["tf"]):
        dvec = _vector(list(counts.keys()), idx["idf"])
        dot = sum(qvec[t] * dvec.get(t, 0.0) for t in qvec)
        if dot > 0:
            scored.append((dot, i))
    scored.sort(reverse=True)
    return [chunks[i] for _, i in scored[:top_k]]


# --------------------------------------------------------------------------
# Ollama embedding backend (local, no API keys)
# --------------------------------------------------------------------------
_OLLAMA_EMBED_MODEL = os.environ.get("VIRGO_EMBED_MODEL", "nomic-embed-text")
_OLLAMA_EMBED_URL = os.environ.get(
    "VIRGO_EMBED_URL", "http://localhost:20128/api/embeddings"
)


def _ollama_embed(text: str) -> list[float] | None:
    """Embed one string via the local Ollama /api/embeddings route."""
    import json
    import urllib.request

    payload = json.dumps(
        {"model": _OLLAMA_EMBED_MODEL, "prompt": text}
    ).encode("utf-8")
    req = urllib.request.Request(
        _OLLAMA_EMBED_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        vec = data.get("embedding")
        if not vec:
            return None
        return [float(x) for x in vec]
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _ollama_build() -> dict | None:
    chunks = _all_chunks()
    if not chunks:
        return {"mtime": _newest_mtime(), "chunks": [], "vectors": []}
    vectors: list[list[float]] = []
    for _, text in chunks:
        v = _ollama_embed(text)
        if v is None:
            return None  # embedder unavailable → signal fallback
        vectors.append(v)
    return {"mtime": _newest_mtime(), "chunks": chunks, "vectors": vectors}


def _ollama_index() -> dict | None:
    global _vec_cache
    with _lock:
        if (
            _vec_cache is None
            or _vec_cache.get("mtime", -1) != _newest_mtime()
        ):
            _vec_cache = _ollama_build()
        return _vec_cache


def _ollama_retrieve(query: str, top_k: int) -> list[tuple[str, str]] | None:
    idx = _ollama_index()
    if idx is None or not idx["chunks"]:
        return None  # None = backend unavailable (caller falls back)
    qv = _ollama_embed(query)
    if qv is None:
        return None
    chunks = idx["chunks"]
    scored: list[tuple[float, int]] = []
    for i, vec in enumerate(idx["vectors"]):
        sim = _cosine(qv, vec)
        if sim > 0:
            scored.append((sim, i))
    scored.sort(reverse=True)
    return [chunks[i] for _, i in scored[:top_k]]


# --------------------------------------------------------------------------
# cognee backend (optional; pure vector retrieval, no graph-LLM build)
# --------------------------------------------------------------------------
def _cognee_retrieve(query: str, top_k: int) -> list[tuple[str, str]] | None:
    """Lazy cognee vector retrieval. Returns None if cognee is unavailable."""
    try:
        import asyncio
        import cognee
        from cognee.modules.search.types import SearchType
    except Exception:
        return None

    env = {
        "EMBEDDING_PROVIDER": "ollama",
        "EMBEDDING_MODEL": _OLLAMA_EMBED_MODEL,
        "EMBEDDING_ENDPOINT": _OLLAMA_EMBED_URL.replace(
            "/api/embeddings", ""
        ),
        "VECTOR_DB_PROVIDER": "lancedb",
        "AUTHENTICATION": "false",
        "DEFAULT_USER_EMAIL": "virgo@local.dev",
        "DEFAULT_USER_PASSWORD": "virgo",
        "CACHING": "false",
    }
    for k, v in env.items():
        os.environ.setdefault(k, v)

    async def _run() -> list[tuple[str, str]]:
        docs = [p.read_text(encoding="utf-8", errors="replace") for p in _iter_documents()]
        if not docs:
            return []
        await cognee.add(docs)
        results = await cognee.search(
            SearchType.CHUNKS, query, top_k=top_k
        )
        out: list[tuple[str, str]] = []
        for r in results[:top_k]:
            text = getattr(r, "text", None) or str(r)
            out.append(("cognee", str(text)))
        return out

    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout=180))
    except Exception:
        return None


# --------------------------------------------------------------------------
# Backend dispatch
# --------------------------------------------------------------------------
_retriever: _Retriever | None = None
_effective_backend: str = "unknown"  # last actually-used backend (after fallback)


def _resolve_retriever() -> _Retriever:
    """Pick the active retriever per VIRGO_RAG_BACKEND, with fallback."""
    backend = _RAG_BACKEND

    def _mark(name: str) -> None:
        global _effective_backend
        _effective_backend = name

    def auto_retrieve(query: str, top_k: int) -> list[tuple[str, str]]:
        # Try ollama first, fall back to tfidf on any failure.
        try:
            res = _ollama_retrieve(query, top_k)
            if res is not None:
                _mark("ollama")
                return res
        except Exception:
            pass
        _mark("tfidf")
        return _tfidf_retrieve(query, top_k)

    def ollama_or_fallback(query: str, top_k: int) -> list[tuple[str, str]]:
        try:
            res = _ollama_retrieve(query, top_k)
            if res is not None:
                _mark("ollama")
                return res
        except Exception:
            pass
        _mark("tfidf")
        return _tfidf_retrieve(query, top_k)

    def cognee_or_fallback(query: str, top_k: int) -> list[tuple[str, str]]:
        try:
            res = _cognee_retrieve(query, top_k)
            if res is not None:
                _mark("cognee")
                return res
        except Exception:
            pass
        _mark("tfidf")
        return _tfidf_retrieve(query, top_k)

    if backend == "tfidf":
        def tfidf_only(query: str, top_k: int) -> list[tuple[str, str]]:
            _mark("tfidf")
            return _tfidf_retrieve(query, top_k)
        return tfidf_only
    if backend == "ollama":
        return ollama_or_fallback
    if backend == "cognee":
        return cognee_or_fallback
    return auto_retrieve  # "auto"


_retriever: _Retriever | None = None


def _get_retriever() -> _Retriever:
    global _retriever
    if _retriever is None:
        _retriever = _resolve_retriever()
    return _retriever


# --------------------------------------------------------------------------
# Public API (unchanged signatures for existing callers)
# --------------------------------------------------------------------------
def retrieve(query: str, top_k: int = 3) -> list[str]:
    """Return the ``top_k`` most relevant KB passages for ``query``.

    Returns an empty list when the KB is empty or nothing matches. Each
    item is a short passage (≤~700 chars) tagged with its source filename.
    """
    hits = _get_retriever()(query, top_k)
    if not hits:
        return []
    out: list[str] = []
    total = 0
    for name, text in hits:
        passage = f"[from {name}]\n{text}"
        if total + len(passage) > _MAX_CONTEXT_CHARS:
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


def active_backend() -> str:
    """Report which backend is actually in use (resolves 'auto'/fallback)."""
    if _effective_backend != "unknown":
        return _effective_backend
    if _RAG_BACKEND in ("tfidf", "ollama", "cognee"):
        return _RAG_BACKEND
    # auto and never called yet: probe ollama reachability cheaply
    try:
        if _ollama_retrieve("probe", 1) is not None:
            return "ollama"
    except Exception:
        pass
    return "tfidf"


def kb_status() -> dict:
    """Return a small status dict for UI / CLI display."""
    docs = _iter_documents()
    idx = _tfidf_index()
    return {
        "kb_dir": str(KB_DIR),
        "backend": active_backend(),
        "doc_count": len(docs),
        "chunk_count": len(idx.get("chunks", [])),
        "ready": len(docs) > 0,
    }


if __name__ == "__main__":
    # Simple self-test / demo
    s = kb_status()
    print(f"KB ready={s['ready']} docs={s['doc_count']} chunks={s['chunk_count']} backend={s['backend']}")
    q = "what are the best research websites"
    hits = retrieve(q, top_k=3)
    if hits:
        print(f"\nTop {len(hits)} hits for: {q!r}\n")
        for h in hits:
            print("-" * 60)
            print(h[:400])
    else:
        print("No KB documents found — drop .md/.txt/.json files into kb/")
