"""
_mem0_memory — persistent agent memory powered by mem0.

Replaces the basic JSON session memory with mem0's cross-session
memory layer, giving Virgo persistent recall, user preferences,
and learning across pipeline runs and chat sessions.

Usage:
    from _mem0_memory import agent_memory
    agent_memory.add("user prefers concise code", session_id="user123")
    results = agent_memory.search("preferences")
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
MEM0_DIR = HERE / ".virgo_mem0"


def _ensure_mem0_config() -> dict:
    """Build a mem0 configuration that stores data locally."""
    MEM0_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": str(MEM0_DIR / "qdrant_db"),
                "collection_name": "virgo_memories",
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": "nomic-embed-text:latest",
                "ollama_base_url": os.environ.get(
                    "OLLAMA_HOST", "http://localhost:11434"
                ),
            },
        },
        "llm": {
            "provider": "ollama",
            "config": {
                "model": os.environ.get("MODEL_GENERATOR", "phi4-mini-reasoning:3.8b"),
                "ollama_base_url": os.environ.get(
                    "OLLAMA_HOST", "http://localhost:11434"
                ),
                "temperature": 0.1,
            },
        },
        "version": "v2.0",
    }


class AgentMemory:
    """Mem0-backed persistent memory for Virgo agents.

    Provides add, search, get_all, and delete operations that
    survive restarts and work across sessions.
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or _ensure_mem0_config()
        self._client: Any = None
        self._ready = False

    @property
    def client(self) -> Any:
        """Lazy-initialize the mem0 Memory client."""
        if self._client is None:
            self._init_client()
        return self._client

    def _init_client(self) -> None:
        try:
            from mem0 import Memory

            self._client = Memory.from_config(self._config)
            self._ready = True
        except Exception as exc:
            print(f"[mem0] init failed: {exc}")
            self._client = None
            self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def add(
        self,
        message: str,
        session_id: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a memory entry.

        Args:
            message: The text content to remember.
            session_id: Logical session or user identifier.
            metadata: Optional dict of structured data (tags, source, etc.).
        """
        if not self.ready:
            return
        try:
            self.client.add(
                messages=message,
                session_id=session_id,
                metadata=metadata or {},
            )
        except Exception as exc:
            print(f"[mem0] add failed: {exc}")

    def search(
        self,
        query: str,
        session_id: str = "default",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search memory entries relevant to a query.

        Returns:
            List of memory entries with 'text', 'score', 'metadata'.
        """
        if not self.ready:
            return []
        try:
            results = self.client.search(
                query=query,
                session_id=session_id,
                limit=limit,
            )
            return results.get("results", []) if isinstance(results, dict) else results
        except Exception as exc:
            print(f"[mem0] search failed: {exc}")
            return []

    def get_all(self, session_id: str = "default") -> list[dict[str, Any]]:
        """Retrieve all memories for a session."""
        if not self.ready:
            return []
        try:
            results = self.client.get_all(session_id=session_id)
            return results if isinstance(results, list) else []
        except Exception as exc:
            print(f"[mem0] get_all failed: {exc}")
            return []

    def delete(self, memory_id: str) -> bool:
        """Delete a specific memory by ID."""
        if not self.ready:
            return False
        try:
            self.client.delete(memory_id=memory_id)
            return True
        except Exception as exc:
            print(f"[mem0] delete failed: {exc}")
            return False

    def clear(self, session_id: str = "default") -> bool:
        """Clear all memories for a session."""
        if not self.ready:
            return False
        try:
            self.client.clear(session_id=session_id)
            return True
        except Exception as exc:
            print(f"[mem0] clear failed: {exc}")
            return False

    def kb_context(self, query: str, top_k: int = 3) -> str:
        """Build a RAG-style context string from relevant memories.

        This is designed to slot into the existing _rag.kb_context()
        interface so it can be used as a drop-in upgrade.
        """
        if not self.ready:
            return ""
        try:
            results = self.search(query, limit=top_k)
            if not results:
                return ""
            parts = []
            for r in results:
                text = ""
                if isinstance(r, dict):
                    text = r.get("text") or r.get("memory", "") or str(r.get("metadata", {}))
                parts.append(text)
            return "\n\n".join(parts[:top_k])
        except Exception:
            return ""


# ── Module-level singleton ────────────────────────────────────────────────
agent_memory = AgentMemory()
