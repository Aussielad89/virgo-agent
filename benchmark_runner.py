"""Run a prompt against every Ollama model via /api/generate."""

import json
import os
import time
import urllib.request
from typing import Any

_OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")


def _available_models() -> list[str]:
    models: list[str] = []
    try:
        with urllib.request.urlopen(f"{_OLLAMA_BASE}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for model in data.get("models") or []:
            name = model.get("name")
            if name:
                models.append(name)
    except Exception:
        pass
    return models


def run_benchmark(prompt: str, models: list[str] | None = None) -> list[dict]:
    if models is None:
        models = _available_models()
    results: list[dict[str, Any]] = []
    for model in models:
        result: dict[str, Any] = {"model": model}
        try:
            body = json.dumps({
                "model": model,
                "prompt": prompt,
                "stream": False,
                "num_predict": 50,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{_OLLAMA_BASE}/api/generate",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            start = time.perf_counter()
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
            latency_ms = (time.perf_counter() - start) * 1000.0
            data = json.loads(raw)
            result.update({
                "latency_ms": latency_ms,
                "tokens": data.get("eval_count", 0),
                "quality": _quality(data),
                "error": None,
            })
        except Exception as exc:
            result.update({
                "latency_ms": None,
                "tokens": None,
                "quality": None,
                "error": str(exc),
            })
        results.append(result)
    return results


def _quality(data: dict) -> float:
    eval_count = data.get("eval_count") or 0
    prompt_eval_count = data.get("prompt_eval_count") or 0
    if prompt_eval_count == 0:
        return 0.0
    return round(min(eval_count / max(prompt_eval_count, 1), 1.0), 4)
