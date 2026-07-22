# Local LLM Setup (this machine)

Virgo routes LLM requests through OmniRoute gateway (http://localhost:20128/v1).
Reference for model selection and
tuning. CPU-only inference — no GPU on this box (i7-12700, 32GB).

## Ollama models available (from /api/tags)
- phi4-mini-reasoning:3.8b — default chat model (fast, reasoning).
- qwen2.5-coder:7b / qwen2.5-coder:14b — code generation (pipeline).
- qwen3.5:2b — light swarmer / fast tasks.
- llama3.2 — general.
- gemma3:4b — general.
- deepseek-r1:1.5b — tiny reasoning.
- ornith — fallback model when others unavailable.

## Env vars (virgo)
- LLM_BASE_URL — OmniRoute gateway endpoint (default http://localhost:20128/v1).
- MODEL_PLANNER / MODEL_GENERATOR / MODEL_FIXER — pipeline role overrides.
- VIRGO_LOG_LEVEL — DEBUG/INFO/WARNING/ERROR.

## Tuning guidance
- No-GPU fine-tune of 3.8B+ is impractical (CPU QLoRA, slow). Prefer:
  1. System-prompt / persona tuning (instant).
  2. RAG over a knowledge base (this kb/ dir) — no training needed.
  3. Real fine-tune only with a specific corpus + patience.
- For research/Q&A, use the "Researcher" persona + this KB.
