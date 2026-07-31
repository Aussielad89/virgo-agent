"""
local_rag.py — Local file indexing and search for Virgo chat.

Extends the KB system with user-defined directories. Type ``/rag-index <path>``
to add a folder to the searchable index, then ask questions in chat and
Virgo will ground answers in your local files.

Commands
---------
/rag-index <path>   Add a directory to the local RAG index
/rag-search <query> Search the local index (returns top hits)
/rag-status         Show what directories are indexed and how many files
/rag-clear          Clear the local index
"""

from __future__ import annotations

import math
import re
import threading
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent

# Local index lives in .virgo_memory/rag_index/
LOCAL_RAG_DIR = HERE / ".virgo_memory" / "rag_index"
_LOCAL_INDEX_FILE = LOCAL_RAG_DIR / "index.json"
_LOCAL_DOCS_FILE = LOCAL_RAG_DIR / "documents.json"

_lock = threading.RLock()
_local_index: dict[str, Any] | None = None


def _ensure_dir() -> None:
    LOCAL_RAG_DIR.mkdir(parents=True, exist_ok=True)


def _load_local_index() -> dict[str, Any]:
    """Load the local RAG index from disk."""
    global _local_index
    with _lock:
        if _local_index is not None:
            return _local_index
        _ensure_dir()
        if _LOCAL_INDEX_FILE.exists():
            try:
                _local_index = _LOCAL_INDEX_FILE.read_text(encoding="utf-8")
                import json
                _local_index = json.loads(_local_index)
            except Exception:
                _local_index = {"dirs": [], "mtime": 0, "chunks": [], "tf": []}
        else:
            _local_index = {"dirs": [], "mtime": 0, "chunks": [], "tf": []}
        return _local_index


def _save_local_index(data: dict[str, Any]) -> None:
    """Persist the local RAG index to disk."""
    global _local_index
    with _lock:
        _ensure_dir()
        import json
        _local_index = data
        _LOCAL_INDEX_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


def _chunk_text(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    chunks: list[str] = []
    step = max(1, size - overlap)
    for i in range(0, len(text), step):
        piece = text[i : i + size]
        if len(piece) >= 40:
            chunks.append(piece)
    return chunks


def _file_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _iter_local_docs(dirs: list[str]) -> list[tuple[str, str]]:
    """Yield (doc_name, content) for all files in indexed directories."""
    docs: list[tuple[str, str]] = []
    for d in dirs:
        p = Path(d)
        if not p.exists() or not p.is_dir():
            continue
        for f in p.rglob("*"):
            if f.is_file() and f.suffix.lower() in (".md", ".txt", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"):
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    docs.append((str(f), content))
                except Exception:
                    pass
    return docs


def _build_local_index(dirs: list[str]) -> dict[str, Any]:
    """Build TF-IDF index over user-specified directories."""
    docs = _iter_local_docs(dirs)
    if not docs:
        return {"dirs": dirs, "mtime": 0, "chunks": [], "tf": [], "vocab": set()}

    tf: list[dict[str, int]] = []
    vocab: set[str] = set()
    chunks: list[tuple[str, str]] = []

    for path, content in docs:
        file_chunks = _chunk_text(content)
        for c in file_chunks:
            chunks.append((path, c))
            counts: dict[str, int] = {}
            for tok in _tokenize(c):
                counts[tok] = counts.get(tok, 0) + 1
                vocab.add(tok)
            tf.append(counts)

    n = len(chunks)
    idf: dict[str, float] = {}
    for tok in vocab:
        df = sum(1 for c in tf if tok in c)
        idf[tok] = math.log((n + 1) / (df + 1)) + 1.0

    mtime = max((_file_mtime(Path(d)) for d in dirs), default=0.0)

    return {"dirs": dirs, "mtime": mtime, "chunks": chunks, "tf": tf, "idf": idf, "vocab": vocab}


def _vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    vec: dict[str, float] = {}
    for t in tokens:
        if t in idf:
            vec[t] = vec.get(t, 0.0) + idf[t]
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm > 0:
        for k in vec:
            vec[k] /= norm
    return vec


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(a.get(t, 0.0) * b.get(t, 0.0) for t in a)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def local_retrieve(query: str, top_k: int = 5) -> list[str]:
    """Search the local RAG index. Returns formatted passages."""
    idx = _load_local_index()
    chunks = idx.get("chunks", [])
    if not chunks:
        return []

    idf = idx.get("idf", {})
    qvec = _vector(_tokenize(query), idf)
    if not qvec:
        return []

    scored: list[tuple[float, int]] = []
    for i, counts in enumerate(idx.get("tf", [])):
        dvec = _vector(list(counts.keys()), idf)
        sim = _cosine(qvec, dvec)
        if sim > 0:
            scored.append((sim, i))
    scored.sort(reverse=True)

    results: list[str] = []
    for _, i in scored[:top_k]:
        path, text = chunks[i]
        short_path = str(Path(path).relative_to(Path.cwd())) if Path(path).is_absolute() else path
        results.append(f"[{short_path}] {text[:300]}...")
    return results


def local_index_dirs() -> list[str]:
    """Return list of currently indexed directories."""
    idx = _load_local_index()
    return list(idx.get("dirs", []))


def local_add_dir(path: str) -> str:
    """Add a directory to the local RAG index. Returns status message."""
    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        return f"Not a directory: {path}"

    idx = _load_local_index()
    dirs = list(idx.get("dirs", []))
    if str(p) in dirs:
        return f"Already indexed: {path}"

    dirs.append(str(p))
    new_idx = _build_local_index(dirs)
    _save_local_index(new_idx)
    return f"Indexed {len(dirs)} director(y/ies), {len(new_idx.get('chunks', []))} chunks"


def local_clear() -> str:
    """Clear the local RAG index."""
    global _local_index
    _ensure_dir()
    if _LOCAL_DOCS_FILE.exists():
        _LOCAL_DOCS_FILE.unlink()
    _save_local_index({"dirs": [], "mtime": 0, "chunks": [], "tf": [], "idf": {}, "vocab": set()})
    return "Local RAG index cleared."


def local_status() -> dict[str, Any]:
    """Return status of the local RAG index."""
    idx = _load_local_index()
    dirs = idx.get("dirs", [])
    chunks = idx.get("chunks", [])
    return {
        "indexed_dirs": dirs,
        "dir_count": len(dirs),
        "chunk_count": len(chunks),
        "ready": len(chunks) > 0,
    }