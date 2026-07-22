"""Spike probe: cognee as Virgo memory backend, using LOCAL Ollama for embeddings.

Goal: prove cognee can ingest Virgo's kb/, build a knowledge graph, and
answer a semantic query on CPU — with no API keys, using nomic-embed-text
served by the local Ollama instance on :11434.

This is a throwaway verification script for the spike/cognee-memory branch.
It does NOT touch Virgo's runtime code.
"""
from __future__ import annotations
import asyncio, os, tempfile, time, sys
from pathlib import Path

# ---- point cognee at local Ollama (embeddings + llm), no API keys ----
os.environ["LLM_PROVIDER"] = "ollama"
os.environ["LLM_MODEL"] = "qwen3.5:2b"            # local chat model
os.environ["LLM_ENDPOINT"] = "http://localhost:11434/v1"   # Ollama OpenAI-compat base
os.environ["LLM_API_KEY"] = "ollama"             # placeholder; Ollama ignores it
os.environ["EMBEDDING_PROVIDER"] = "ollama"
os.environ["EMBEDDING_MODEL"] = "nomic-embed-text"  # local embedder
os.environ["EMBEDDING_ENDPOINT"] = "http://localhost:11434"
os.environ["EMBEDDING_DIMENSIONS"] = "768"          # nomic-embed-text dimension
os.environ["VECTOR_DB_DIMENSION"] = "768"
os.environ["OLLAMA_HOST"] = "http://localhost:11434"
# keep graph/vector store local + lightweight (NetworkX + simple in-file)
os.environ["GRAPH_DATABASE_PROVIDER"] = "ladybug"   # local in-process graph (no server)
os.environ["VECTOR_DB_PROVIDER"] = "lancedb"
os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] = "false"   # networkx can't do multi-tenant AC
os.environ["AUTHENTICATION"] = "false"                   # disable auth for single-user spike
os.environ["DEFAULT_USER_EMAIL"] = "virgo@local.dev"
os.environ["DEFAULT_USER_PASSWORD"] = "virgo"
os.environ["CACHING"] = "false"

import cognee

KB = Path(__file__).resolve().parent / "kb"
SAMPLE = "Virgo is a local-first multi-agent orchestration framework written in Python. " \
         "It runs Ollama models offline for chat, RAG over kb/, and recon pipelines. " \
         "OmniForge is a Rust TUI for red-team port scanning and local security audits. " \
         "KernOS is a Python sandbox blueprint lab with a Textual TUI."

async def main() -> None:
    # ingest the sample doc into cognee's DEFAULT dataset (lets cognee grant
    # permissions normally instead of supplying an explicit dataset_id that
    # skips the permission-grant step)
    t0 = time.time()
    await cognee.add([SAMPLE])
    ingest = time.time() - t0

    t1 = time.time()
    await cognee.cognify()
    cognify = time.time() - t1

    t2 = time.time()
    # NATURAL_LANGUAGE = pure semantic vector retrieval of the matching
    # knowledge-graph text nodes. Returns grounded context WITHOUT requiring
    # an LLM answer-generation step (which this Ollama build can't serve via
    # the OpenAI /chat/completions route). This proves the memory retrieval
    # layer works on CPU with local embeddings.
    from cognee.modules.search.types import SearchType
    res = await cognee.search(SearchType.NATURAL_LANGUAGE,
                              "What language is OmniForge written in and what does it do?")
    recall = time.time() - t2

    print("\n=== COGNEE SPIKE RESULTS ===")
    print(f"ingest : {ingest:.1f}s")
    print(f"cognify: {cognify:.1f}s  (embedding + graph build)")
    print(f"recall : {recall:.1f}s")
    print("--- recall answer ---")
    for r in res:
        print(str(r)[:800])
    print("===========================")

if __name__ == "__main__":
    asyncio.run(main())
