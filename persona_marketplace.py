"""Fetch/import personas from URL with caching in .virgo_memory/personas/."""

import hashlib
import json
import os
import urllib.request
from pathlib import Path

_ROOT = Path(".virgo_memory")
_CACHE_DIR = _ROOT / "personas"


def _ensure_dirs() -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def list_personas(index_url: str) -> list[dict]:
    _ensure_dirs()
    try:
        with urllib.request.urlopen(index_url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch index: {exc}") from exc
    personas = data if isinstance(data, list) else data.get("personas") or []
    validated: list[dict] = []
    for p in personas:
        if isinstance(p, dict) and _is_valid(p):
            validated.append(p)
    return validated


def import_persona(url: str) -> dict:
    _ensure_dirs()
    cache_path = _CACHE_DIR / f"{_url_hash(url)}.json"
    if cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if _is_valid(data):
            return data
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch persona: {exc}") from exc
    if not _is_valid(data):
        raise ValueError("Persona missing required fields: name, prompt, model")
    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def _is_valid(persona: dict) -> bool:
    return all(k in persona for k in ("name", "prompt", "model"))
