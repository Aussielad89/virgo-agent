# Virgo — Multi-Agent State Machine

![test](https://github.com/Aussielad89/virgo-agent/actions/workflows/test.yml/badge.svg)
An autonomous code-generation pipeline with diagnostics, network scanning,
alerting, web search, project scaffolding, and system monitoring tools.

## Autonomous Agent Runtime

Beyond generating code, Virgo can **accomplish goals autonomously** — a
ReAct loop that reasons, acts through real tools, observes results, reflects,
and self-evaluates until the goal is met.

```bash
# Run the autonomous agent (deterministic, no LLM needed)
virgo agent --goal "write a file report.txt summarising mock_logs.txt"

# With a local LLM (Ollama / any OpenAI-compatible endpoint)
virgo agent --llm --goal "write fizzbuzz.py for 1..20, then run it to confirm"
```

**How it works:** `plan → act → observe → reflect → evaluate`, budgeted by
`--steps` and `--retries`. One tool call per turn keeps the agent grounded in
real observations instead of hallucinated ones.

| Piece | Module | Role |
|-------|--------|------|
| Tool layer | `tools_core.py` | `shell`, `file_read`, `file_write`, `python_run`, `web_fetch`, `think` (stdlib-only, sandboxed) |
| MCP bridge | `mcp_bridge.py` | Exposes MCP servers as tools (auto-discovered from standard configs) |
| Experience memory | `experience.py` | Recalls lessons from past runs, feeds them into the prompt |
| Quality gate | `evaluator.py` | Deterministic + LLM rubric scoring — decides real success |
| Runtime | `agent_runtime.py` | The ReAct loop tying it all together |

Flags: `--llm`, `--steps N`, `--retries N`, `--no-mcp`, `--mcp 'name=cmd args'`,
`--no-experience`, `--stream`/`--no-stream`.

## Quick Start

```bash
# Install
pip install -e .

# Run the TUI dashboard
virgo-dashboard

# List available project scaffolds
virgo scaffold

# Generate a FastAPI CRUD API
virgo scaffold fastapi-crud --output ./myapi --var project_name=myapi

# Run the pipeline with deterministic policies
virgo run --goal "parse mock_logs.txt"

# Run with LLM-backed policies (requires Ollama)
virgo run --llm --goal "build a web scraper"
```

## Commands

| Command | Description |
|---------|-------------|
| `virgo run` | Run the pipeline (discover → plan → generate → test → fix) |
| `virgo agent` | Autonomous ReAct runtime — accomplishes goals via real tools |
| `virgo serve` | Launch the web dashboard |
| `virgo list` | List saved sessions |
| `virgo replay <session>` | Replay a saved session |
| `virgo feedback` | Show learned fix patterns |
| `virgo templates` | Generate code from templates |
| `virgo export <session>` | Export session as HTML/Markdown |
| `virgo demo` | Run the demo pipeline (deterministic policies) |
| `virgo plugins` | List/load plugins |
| `virgo scaffold` | List/generate project scaffolds |
| `virgo-dashboard` | TUI dashboard with 22 tools |

## Project Scaffolds

Generate full project skeletons from scaffold definitions in `scaffolds/*.json`:

```bash
virgo scaffold                           # List available scaffolds
virgo scaffold fastapi-crud              # Show details
virgo scaffold cli-app -o ./mycli        # Generate CLI app
virgo scaffold flask-app -o ./myweb      # Generate Flask web app
virgo scaffold python-lib -o ./mylib     # Generate Python library
virgo scaffold agent-tool -o .           # Generate virgo module
```

| Scaffold | Files | Description |
|----------|-------|-------------|
| `fastapi-crud` | 11 | FastAPI CRUD API with SQLAlchemy + SQLite + Pydantic schemas |
| `cli-app` | 8 | Python CLI with argparse, entry point, tests |
| `flask-app` | 7 | Flask web app with Jinja2 templates + static CSS |
| `python-lib` | 8 | Reusable library with pyproject.toml + CI config + tests |
| `agent-tool` | 2 | New virgo_*.py framework module + test |

Add new scaffolds by dropping a `.json` file into `scaffolds/` — no code changes needed.

## TUI Dashboard Options

| Option | Tool | Description |
|--------|------|-------------|
| 1 | `virgo_network_scanner.py` | Subnet device discovery |
| 2 | `virgo_diagnostics.py` | System health + log analysis |
| 3 | `virgo_alerts.py` | Alert evaluation engine |
| 4 | `virgo_fixer.py` | Auto-remediation of alerts |
| 5 | `workflow_check.py` | Connectivity / environment check |
| 6 | `virgo_web_search.py` 1 | DuckDuckGo search |
| 7 | `virgo_web_search.py` 2 | Google search |
| 8 | `virgo_web_search.py` 3 | YouTube search |
| 9 | Pipeline | Launch core agent pipeline |
| 10-12 | Viewer | View network map, alerts, search history |
| 13 | `virgo_fingerprinter.py` | TCP banner grabber |
| 14 | `virgo_webhook.py` | Dispatch telemetry (file or HTTP POST) |
| 15 | `virgo_sandbox.py` | Restricted command execution |
| 16 | `virgo_watchdog.py` | Scheduled diag → alerts → fixer runner |
| 17 | Scaffold list | List available scaffolds |
| 18-22 | Scaffolds | Generate FastAPI / CLI / Flask / lib / tool |

## Data Chain

```
virgo_network_scanner → virgo_network_map.json → virgo_alerts → ALERTS_TRIGGERED.txt → virgo_fixer
virgo_diagnostics     → virgo_full_report.json → virgo_alerts ─┘
```

## Architecture

```
                    ┌──────────────┐
                    │    CLI/TUI   │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┬──────────────┐
              ▼            ▼            ▼              ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
       │Pipeline  │ │Diagnostics│ │ Web     │ │ Scaffold     │
       │Orchestr. │ │Modules   │ │ Search  │ │ Engine       │
       └──────────┘ └──────────┘ └──────────┘ └──────────────┘

Pipeline: Discover → Plan → Generate → Critic → Deps → Test/Fix Loop
```

## Testing

```bash
pip install -e .[dev]
python -m pytest tests/ -v            # 276 tests
python -m pytest tests/ --cov=.       # With coverage
```

## Desktop App (PyQt6)

A full GUI (`virgo_desktop.py`) with sidebar navigation, theming, and live
pipeline/swarm monitoring. Requires PyQt6 (PyQt6 6.11 under `C:/Python314` on
this machine):

```bash
C:/Python314/python.exe virgo_desktop.py
# or with the bundled interpreter:
python virgo_desktop.py
```

**Features**
- **Sidebar** pages: Pipeline, Chat, Files, Network, Diagnostics, Alerts,
  Scaffolds, Sessions, Swarm, Logs, Plugins, Settings, Procs, Bench.
- **Theming** — Mocha / Latte / Nord / Gruvbox built in, plus a live theme
  editor (pick colours → save as a new theme) and custom CSS injection.
  Theme + mode persist to `.virgo_desktop_config.json`.
- **Pop-out** any page into its own window (Ctrl+P → select → Pop out).
- **Command palette** (`Ctrl+Shift+P`) — fuzzy search pages *and* actions
  (Run Pipeline, Export Chat, Toggle Theme, Quit, …).
- **Chat** — slash autocomplete, branching, regeneration, Ctrl+F search,
  persona switcher, streaming token rate, voice mode, A/B model compare,
  multi-model parallel chat, image drag-drop + gallery.
- **Pipeline** — live DAG visualiser (discover → plan → generate → test → fix),
  click a node to re-run that phase, export the graph as PNG.
- **Files** — tree browser + Git panel (status / commit / push).
- **Logs** — level filter + regex filter + tail-follow.
- **Procs** — live python/ollama process table with kill button.
- **Bench** — benchmark Ollama models on a standard prompt (latency/token table).
- **Toasts** + tray notifications on pipeline/swarm completion; completion chime.
- **Persistence** — window geometry, sidebar order/collapse, last page, and
  per-page splitter positions are restored on launch.

Config files (all gitignored):

| File | Purpose |
|------|---------|
| `.virgo_desktop_config.json` | Theme, mode, sidebar order/collapse, last page |
| `.virgo_desktop_geom.json` | Window X/Y/W/H |
| `.virgo_pipeline_ui.json` | Pipeline splitter sizes |
| `.virgo_themes.json` | User-saved custom themes |
| `.virgo_chat_history/` | Chat sessions |
| `.virgo_prompts/` | Saved prompt templates |

## Build

Library / CLI wheel:

```bash
pip install build
python -m build
pip install dist/virgo_agent-*.whl
```

Standalone desktop executable (PyInstaller, uses `logo.ico`):

```bash
pip install pyinstaller
pyinstaller virgo_desktop.spec
# → dist/virgo_desktop/virgo_desktop.exe
```

## Changelog

### v0.2.x — Desktop UI overhaul
- PyQt6 desktop app (`virgo_desktop.py`) with 14 sidebar pages.
- Data-driven theme system: Mocha / Latte / Nord / Gruvbox, live theme editor,
  custom CSS injection, persisted to `.virgo_desktop_config.json`.
- Pop-out pages into separate windows; theme/CSS apply live to popped windows.
- Command palette (`Ctrl+Shift+P`) for pages **and** actions; page quick-nav
  (`Ctrl+P`).
- Chat: slash autocomplete, branching, regeneration, Ctrl+F search, persona
  switcher, streaming token rate, voice mode, A/B compare, multi-model chat,
  image drag-drop + gallery, font zoom, markdown export, split-view.
- Pipeline: live DAG visualiser with per-phase re-run and PNG export.
- Files: tree browser + Git panel (status / commit / push).
- Logs: level + regex filter, tail-follow.
- Procs monitor (kill button), port scanner, benchmark runner, .env editor.
- Toasts + tray notifications, completion chime.
- Persisted layout: geometry, sidebar order/collapse, last page, splitter sizes.

## Environment Variables

See `.env.example` — configures logging level/file, webhook URL, watchdog interval,
and LLM endpoint for `--llm` mode.

## Search Engines

- DuckDuckGo — no API key required
- Google — HTML scraping (may be blocked, falls back gracefully)
- YouTube — HTML scraping, returns video IDs and watch URLs
