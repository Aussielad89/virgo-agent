# Virgo Agent Framework

Virgo is a local-first multi-agent code-generation pipeline + system
monitoring framework, authored by Aussielad89 (Mikey). It runs entirely on
the user's Windows machine via Ollama (local LLMs, no cloud).

## Components
- Pipeline mode (`virgo run`): 4-phase state machine — DISCOVER → PLAN →
  GENERATE → WTF loop (Write/Test/Fix) until tests pass.
- Dashboard mode (`virgo-dashboard`): TUI for network scan, diagnostics,
  alerts, auto-fix, web search, scaffolding.
- Desktop GUI (`virgo_desktop.py`): PyQt6 chat + pipeline UI.
- Chat: slash commands /help /tools /clear /read <path> /web <url> /py <code>.
- LLM backends: OmniRoute gateway (default, localhost:20128), vLLM, LM Studio, or the
  Crush CLI. Default chat model: phi4-mini-reasoning:3.8b.

## Environment
- No GPU on this machine (i7-12700, 32GB RAM). CPU-only inference.
- Repo hygiene rule: never litter the repo root with runtime artifacts; route
  generated output to gitignored dirs (output/, .virgo_memory/, .virgo_chat_history/).
- Secrets (Telegram tokens etc.) must never be committed.

## User preferences
- Prefers concise, direct answers; impatient with verbose explanations.
- Likes parallel/swarm execution for multi-part tasks.
- Into red-teaming / offensive security (nmap, amass, nuclei, Covenant C2).
- Likes ranked options when asked to recommend.
