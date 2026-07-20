"""Tests for the _rag RAG layer.

Covers both retrieval backends and the graceful fallback chain:

* TF-IDF backend (zero deps) — always testable.
* Ollama embedding backend — tested live when a local Ollama embedder is
  reachable; skipped otherwise so CI without Ollama still passes.
* ``auto`` / ``ollama`` fallback to TF-IDF when the embedder is down.
* ``VIRGO_RAG_BACKEND`` env switching.
* ``kb_context`` formatting and empty-KB graceful degradation.

No API keys are required for any test.
"""

from __future__ import annotations

import importlib
import os
import textwrap
from pathlib import Path

import pytest

import _rag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_kb(tmp_path: Path, docs: dict[str, str]) -> Path:
    kb = tmp_path / "kb"
    kb.mkdir()
    for name, content in docs.items():
        (kb / name).write_text(content, encoding="utf-8")
    return kb


def _reload_with(kb_dir: Path, backend: str):
    """Reload _rag pointed at a temp KB with a chosen backend env."""
    os.environ["VIRGO_RAG_BACKEND"] = backend
    mod = importlib.reload(_rag)
    mod.KB_DIR = kb_dir
    mod.PRIVATE_DIR = kb_dir / "private"
    # force re-resolution + cache drop
    mod._cache = None
    mod._vec_cache = None
    mod._retriever = None
    mod._effective_backend = "unknown"
    return mod


SAMPLE_KB = {
    "gpu.md": textwrap.dedent(
        """
        # GPU compute
        CUDA cores accelerate matrix multiplication for deep learning
        training. An NVIDIA RTX 4090 delivers 16384 cuda cores.
        """
    ),
    "cats.md": textwrap.dedent(
        """
        # Cats
        Domestic cats are small carnivorous mammals. They purr when
        content and knead soft surfaces with their paws.
        """
    ),
    "rust.md": textwrap.dedent(
        """
        # Rust language
        Rust is a systems programming language focused on memory safety
        without a garbage collector. Cargo is its build tool.
        """
    ),
}


# ---------------------------------------------------------------------------
# TF-IDF backend
# ---------------------------------------------------------------------------
def test_tfidf_retrieves_relevant_doc(tmp_path):
    kb = _make_kb(tmp_path, SAMPLE_KB)
    mod = _reload_with(kb, "tfidf")
    hits = mod.retrieve("rust programming language cargo", top_k=2)
    assert hits, "expected at least one hit"
    assert any("Rust" in h for h in hits), hits
    assert all(h.startswith("[from ") for h in hits)


def test_tfidf_empty_kb_returns_empty(tmp_path):
    kb = _make_kb(tmp_path, {})  # empty KB dir
    mod = _reload_with(kb, "tfidf")
    assert mod.retrieve("anything") == []
    assert mod.kb_context("anything") == ""
    assert mod.kb_status()["ready"] is False


def test_tfidf_kb_context_format(tmp_path):
    kb = _make_kb(tmp_path, SAMPLE_KB)
    mod = _reload_with(kb, "tfidf")
    ctx = mod.kb_context("tell me about cats")
    assert ctx.startswith("=== KNOWLEDGE BASE")
    assert "=== END KNOWLEDGE BASE ===" in ctx
    assert "[from cats.md]" in ctx


# ---------------------------------------------------------------------------
# Ollama backend + fallback
# ---------------------------------------------------------------------------
def _ollama_reachable() -> bool:
    try:
        return _rag._ollama_embed("probe") is not None
    except Exception:
        return False


def test_ollama_fallback_to_tfidf_when_embedder_down(tmp_path, monkeypatch):
    """With backend=ollama but a dead embedder, retrieval still works (tfidf)."""
    kb = _make_kb(tmp_path, SAMPLE_KB)
    mod = _reload_with(kb, "ollama")
    # Force the embedder to fail.
    monkeypatch.setattr(mod, "_ollama_embed", lambda text: None)
    # rebuild vector cache so _ollama_retrieve returns None
    mod._vec_cache = {"mtime": -1, "chunks": [], "vectors": []}
    hits = mod.retrieve("rust cargo build tool", top_k=2)
    assert hits, "fallback to tfidf should still return hits"
    assert mod.active_backend() == "tfidf"


def test_auto_fallback_when_forced_down(tmp_path, monkeypatch):
    kb = _make_kb(tmp_path, SAMPLE_KB)
    mod = _reload_with(kb, "auto")
    monkeypatch.setattr(mod, "_ollama_embed", lambda text: None)
    mod._vec_cache = {"mtime": -1, "chunks": [], "vectors": []}
    hits = mod.retrieve("domestic cats purr", top_k=2)
    assert hits
    assert any("cats" in h.lower() for h in hits)


@pytest.mark.skipif(
    not _ollama_reachable(),
    reason="local Ollama embedder (nomic-embed-text) not reachable",
)
def test_ollama_live_semantic_retrieval(tmp_path):
    """Live: Ollama embeddings retrieve the semantically-correct doc."""
    kb = _make_kb(tmp_path, SAMPLE_KB)
    mod = _reload_with(kb, "ollama")
    hits = mod.retrieve("graphics card for neural network training", top_k=1)
    assert hits, "expected a semantic hit"
    # "graphics card for neural network training" should map to the GPU doc,
    # not the cats or rust docs.
    assert "gpu.md" in hits[0], hits
    assert mod.active_backend() == "ollama"


# ---------------------------------------------------------------------------
# Backend switching / env validation
# ---------------------------------------------------------------------------
def test_unknown_backend_defaults_to_auto(tmp_path, monkeypatch):
    kb = _make_kb(tmp_path, SAMPLE_KB)
    mod = _reload_with(kb, "bogus-backend-name")
    # resolve retriever should not raise and should still retrieve via fallback
    hits = mod.retrieve("rust cargo", top_k=1)
    assert hits


def test_kb_status_reports_backend(tmp_path):
    kb = _make_kb(tmp_path, SAMPLE_KB)
    mod = _reload_with(kb, "tfidf")
    status = mod.kb_status()
    assert status["backend"] == "tfidf"
    assert status["doc_count"] == 3
    assert status["ready"] is True


def test_retrieve_respects_context_char_budget(tmp_path):
    # Build a KB whose chunks would overflow _MAX_CONTEXT_CHARS if all returned.
    big = "\n".join(f"line {i} about rust cargo build tooling" for i in range(200))
    kb = _make_kb(tmp_path, {"rust.md": big})
    mod = _reload_with(kb, "tfidf")
    hits = mod.retrieve("rust cargo", top_k=50)
    total = sum(len(h) for h in hits)
    assert total <= mod._MAX_CONTEXT_CHARS + 1
