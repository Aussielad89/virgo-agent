"""Spike probe #2 — isolate cognee's RETRIEVAL layer (no graph-LLM build).

cognee.cognify() builds the knowledge graph and needs the LLM; this Ollama
build only serves /api/generate (not the OpenAI /v1/chat/completions route
cognee's adapter uses), so full cognify can't complete here. This probe proves
the part that matters for "is cognee a good memory backend": local embeddings
+ semantic vector retrieval over Virgo's kb content, on CPU, no API keys.
"""
from __future__ import annotations
import asyncio, os, time

os.environ["LLM_PROVIDER"] = "ollama"
os.environ["LLM_MODEL"] = "qwen3.5:2b"
os.environ["LLM_ENDPOINT"] = "http://localhost:11434/v1"
os.environ["LLM_API_KEY"] = "ollama"
os.environ["EMBEDDING_PROVIDER"] = "ollama"
os.environ["EMBEDDING_MODEL"] = "nomic-embed-text"
os.environ["EMBEDDING_ENDPOINT"] = "http://localhost:11434"
os.environ["EMBEDDING_DIMENSIONS"] = "768"
os.environ["VECTOR_DB_DIMENSION"] = "768"
os.environ["GRAPH_DATABASE_PROVIDER"] = "ladybug"
os.environ["VECTOR_DB_PROVIDER"] = "lancedb"
os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] = "false"
os.environ["AUTHENTICATION"] = "false"
os.environ["DEFAULT_USER_EMAIL"] = "virgo@local.dev"
os.environ["DEFAULT_USER_PASSWORD"] = "virgo"
os.environ["CACHING"] = "false"

import cognee
from cognee.modules.search.types import SearchType

DOCS = [
    "Virgo is a local-first multi-agent orchestration framework written in Python.",
    "OmniForge is a Rust TUI for red-team port scanning and local security audits.",
    "KernOS is a Python sandbox blueprint lab with a Textual TUI for managing blueprints.",
    "Virgo runs Ollama models offline for chat, RAG over kb/, and recon pipelines.",
]

async def main() -> None:
    t0 = time.time()
    await cognee.add(DOCS)
    ingest = time.time() - t0

    # CHUNKS = pure semantic vector retrieval (no graph-LLM completion step)
    t1 = time.time()
    res = await cognee.search(SearchType.CHUNKS, "What language is OmniForge and what is it for?")
    search = time.time() - t1

    print("\n=== COGNEE RETRIEVAL SPIKE ===")
    print(f"ingest : {ingest:.1f}s  ({len(DOCS)} docs)")
    print(f"search : {search:.1f}s")
    print(f"hits   : {len(res)}")
    print("--- top retrieved chunks ---")
    for r in res[:3]:
        text = getattr(r, "text", None) or str(r)
        print(" •", str(text)[:160])
    print("=============================")

if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=150))
