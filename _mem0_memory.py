import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import Any, Optional

class SQLiteMemoryCache:
    def __init__(self, db_path: str = '~/.hermes/agent_memory.db'):
        self.db_path = os.path.expanduser(db_path)
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS memory (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    timestamp DATETIME,
                    ttl INTEGER  -- seconds
                )
            ''')
    
    def set(self, key: str, value: Any, ttl_seconds: int = 3600):
        value_str = json.dumps(value)
        timestamp = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'INSERT OR REPLACE INTO memory (key, value, timestamp, ttl) VALUES (?, ?, ?, ?)',
                (key, value_str, timestamp, ttl_seconds)
            )
    
    def get(self, key: str) -> Optional[Any]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT value, timestamp, ttl FROM memory WHERE key = ?', (key,))
            if row := cur.fetchone():
                value, timestamp, ttl = row
                if ttl and (datetime.utcnow() - datetime.fromisoformat(timestamp)) > timedelta(seconds=ttl):
                    return None  # Expired
                return json.loads(value)
    
    def cleanup(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                DELETE FROM memory
                WHERE ttl > 0
                AND datetime(timestamp, '+', ttl, 'second') < datetime('now')
            """)
    
    def get_all(self) -> list[tuple[str, Any]]:
        self.cleanup()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute('SELECT key, value FROM memory')
            return [(key, json.loads(value)) for key, value in cur.fetchall()]

# ExperienceMemory integration
class ExperienceMemory:
    def __init__(self):
        self._cache = SQLiteMemoryCache()
    
    def store(self, key: str, data: Any, ttl: int = 3600):
        self._cache.set(key, data, ttl)
    
    def recall(self, key: str) -> Optional[Any]:
        return self._cache.get(key)
    
    def get_all(self) -> list[tuple[str, Any]]:
        return self._cache.get_all()

# Maintain mem0 API compatibility for existing code
class AgentMemory:
    def __init__(self, config: dict | None = None):
        self._cache = SQLiteMemoryCache()
    
    def add(self, message: str, session_id: str = "default", metadata: dict[str, Any] | None = None):
        key = f"{session_id}:{message[:20]}"
        self._cache.set(key, message, 86400)  # 1 day TTL
    
    def search(self, query: str, session_id: str = "default", limit: int = 5):
        return [
            {"text": v, "score": 1.0, "metadata": {}}
            for k, v in self._cache.get_all()
            if session_id in k and query.lower() in k.lower()
        ][:limit]
    
    def get_all(self, session_id: str = "default"):
        return [
            {"text": v, "metadata": {}}
            for k, v in self._cache.get_all()
            if session_id in k
        ]
    
    def delete(self, memory_id: str) -> bool:
        self._cache.set(memory_id, None, 0)  # Delete by setting TTL=0
        return True
    
    def clear(self, session_id: str = "default") -> bool:
        for k, _ in self._cache.get_all():
            if session_id in k:
                self._cache.set(k, None, 0)
        return True
    
    def kb_context(self, query: str, top_k: int = 3) -> str:
        results = self.search(query, limit=top_k)
        return "\n\n".join(r["text"] for r in results)

# Module-level singleton
agent_memory = AgentMemory()