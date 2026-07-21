# Changelog

All notable changes to virgo-agent are documented here.

## 0.6.0 (2026-07-21)

### Added
- Semantic RAG backend (`_rag.py`) with Ollama embeddings (`nomic-embed-text`), TF-IDF fallback, and optional cognee graph store. Set `VIRGO_RAG_BACKEND` to `tfidf`, `ollama`, `cognee`, or `auto`.
- `kb/` knowledge base directory for grounded chat retrieval — drop `.md`, `.txt`, or `.json` files to teach Virgo about your projects.
- Desktop GUI environment page fixes (smear, stylesheet parse spam).

### Fixed
- `.env` encoding crash on CI — `_save()` and `_save_env()` now write UTF-8 instead of cp1252 default, preventing dotenv parse failures.
- CI test collection — `test_desktop.py` (PyQt6) and `test_server.py` (fastapi/pydantic_core) excluded from the default pytest run so missing optional deps do not crash the suite.
- Chat test timeout on CI — `TestChat` class skipped when `CI` env is set (no LLM reachable).
- CI matrix fail-fast disabled so all jobs report independently.

### Changed
- Version bumped from 0.5.1 to 0.6.0

## 0.5.1 (2026-07-16)

### Added
- First-class `python-dotenv` dependency in `pyproject.toml`
- Ruff linting step in CI workflow
- Python 3.14 to CI test matrix
- Docker healthcheck and missing source files (`generators`, `subagent`, `virgo_diff`, `virgo_git`, `virgo_init`, `virgo_testgen`, `virgo_watcher`, `tools_core`)
- Tests for `virgo_alerts` and `virgo_run` modules
- CHANGELOG.md

### Fixed
- `ModuleNotFoundError: dotenv` in `virgo config` commands
- Broken `_supports_emoji` import in `test_orchestrator_pytest.py`
- 154 ruff lint issues across all modules (unused imports, ambiguous names, lambda assignments, unused variables, undefined names)
- Test count in README (51 → 276)

### Changed
- Version bumped from 0.5.0 to 0.5.1
- CI install uses `.[dev,yaml,web]` extras instead of manual requirements.txt
- Docker build installs with `.[web,yaml]` for full functionality
- `setup.py` includes all currently shipped modules

## 0.5.0 (2025-06-xx)

### Added
- Autonomous ReAct agent runtime (`agent_runtime.py`)
- MCP bridge (`mcp_bridge.py`) for external tool servers
- Experience memory (`experience.py`) — learns from past runs
- Quality evaluator (`evaluator.py`) — deterministic + LLM scoring
- Dockerfile for containerized dashboard deployment
- CI workflows: `test.yml` and `release.yml`
- Project scaffold system (`virgo_scaffold.py`) with FastAPI, CLI, Flask, library, and agent-tool templates
- Code critic (`critic.py`) — AST-based static analysis
- Auto-dependency installer (`autodepend.py`)
- TUI dashboard (`virgo_menu.py`) with 22 tools
- Web dashboard (`server.py`) — FastAPI + HTMX
- Web search (DuckDuckGo, Google, YouTube)
- Network scanner, system diagnostics, alert engine, auto-fixer
- Webhook dispatch, sandboxed command execution, watchdog
- `virgo diff`, `virgo git`, `virgo init`, `virgo watch`, `virgo docgen`, `virgo testgen`
- 276 unit tests (pytest)
