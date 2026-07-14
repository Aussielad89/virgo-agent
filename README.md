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
python -m pytest tests/ -v        # 51 tests
python -m pytest tests/ --cov=.   # With coverage
```

## Build

```bash
pip install build
python -m build
pip install dist/virgo_agent-*.whl
```

## Environment Variables

See `.env.example` — configures logging level/file, webhook URL, watchdog interval,
and LLM endpoint for `--llm` mode.

## Search Engines

- DuckDuckGo — no API key required
- Google — HTML scraping (may be blocked, falls back gracefully)
- YouTube — HTML scraping, returns video IDs and watch URLs
