# Changelog

All notable changes to virgo-agent are documented here.

## 0.7.0 (2026-07-24)

### Added
- **Agent Memory & Learning Engine** (`learning_engine.py`) — persistent SQLite-backed learning that records outcomes per task type, auto-injects relevant lessons into new runs, and improves planning/generation/fixing over time. CLI: `virgo memory list|show|search|stats|prune|record`
- **Plugin SDK** (`virgo plugin create`) — scaffold generator for new plugins, hot-reload support, `__plugin_meta__` metadata system, plugin install command. New scaffold: `plugin`
- **Telegram Bot** (`virgo_bot.py`, `telegram_bot_plugin.py`) — full bot with `/run`, `/chat`, `/alerts`, `/search` commands. Pure-urllib fallback mode (no deps required) or full `python-telegram-bot` backend. CLI: `virgo bot start|stop|status`
- **Multi-modal Media Analyzer** (`virgo_media.py`) — file type detection via magic bytes, image analysis (PIL or header-based), PDF text extraction (PyMuPDF or pdftotext), audio metadata (mutagen or WAV header). CLI: `virgo analyze <file>` with `--json`, `--vision`, `--deep` flags
- `media_analyzer` tool registered in the tool registry
- `file_sampler` now delegates to `virgo_media` for image/PDF/audio files
- `[bot]` and `[media]` optional dependency groups in `pyproject.toml`
- Desktop test fix — skip PyQt6-dependent tests when PyQt6 not installed

### Changed
- Version bumped from 0.6.0 to 0.7.0
- `setup.py` includes all new modules (`learning_engine`, `virgo_media`, `virgo_bot`, `telegram_bot_plugin`, `_rag`)

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
