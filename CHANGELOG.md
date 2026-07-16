# Changelog

All notable changes to virgo-agent are documented here.

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
