# AGENTS.md — virgo-agent

## Project overview

Virgo is an autonomous multi-agent code-generation pipeline and system
monitoring framework. It has two personalities:

1. **Pipeline mode** (`virgo run`): A 4-phase state machine that discovers
   files in the workspace, plans what to build, generates code, then enters
   a Write-Test-Fix (WTF) loop until tests pass or iterations are exhausted.
2. **Dashboard mode** (`virgo-dashboard` / `virgo_menu.py`): TUI menu for
   network scanning, system diagnostics, alert evaluation, auto-fix, web
   search, and launching the pipeline.

## Repository structure

```
agent-framework/
├── _console.py               # Shared emoji→ASCII helpers (Windows-safe)
├── _log.py                   # Logging setup (reads VIRGO_LOG_LEVEL, VIRGO_LOG_FILE)
├── cli.py                    # Unified CLI: run / serve / replay / list / feedback / demo
├── run.py                    # Demo runner with deterministic policies (log parser) — legacy
├── main.py                   # LLM-powered pipeline policies (Ollama-compatible)
├── orchestrator.py           # 4-phase state machine (core)
├── tools.py                  # Tool registry: file_sampler, code_patcher, web_fetch, etc.
├── environment.py            # Isolated agent_env virtualenv manager
├── memory.py                 # Session persistence (JSON), replay, feedback learning
├── critic.py                 # AST-based static analysis for generated code
├── autodepend.py             # Auto-install missing third-party packages
├── config.py                 # JSON/YAML pipeline configuration loader
├── plugins.py                # Dynamic plugin loader (scan for *_plugin.py)
├── server.py                 # FastAPI + HTMX web dashboard (optional deps)
├── exporter.py               # HTML/Markdown report export
├── templates.py              # Code template engine
├── workflow.py               # Pipeline graph rendering
├── workflow_check.py         # Connectivity/environment check script
├── virgo_menu.py             # TUI master dashboard (config-driven via dashboard.json)
├── virgo_network_scanner.py  # /24 subnet device discovery
├── virgo_diagnostics.py      # System health + log analysis
├── virgo_alerts.py           # Alert engine (evaluates reports)
├── virgo_fixer.py            # Auto-remediation of known alerts
├── virgo_fingerprinter.py    # TCP banner grabber (connect, send HTTP GET, read headers)
├── virgo_scaffold.py         # Project scaffolding engine (reads scaffolds/*.json)
├── virgo_webhook.py          # Build + dispatch telemetry (file or real HTTP POST)
├── virgo_sandbox.py          # Restricted command sandbox (blocklist-based)
├── virgo_watchdog.py         # Scheduled watchdog: diagnostics→alerts→fixer on a timer
├── virgo_web_search.py       # DuckDuckGo / Google / YouTube search
├── logo.py                   # ASCII banner (pure ASCII — always safe)
├── logo.svg                  # SVG version of logo
├── dashboard.json            # Structured menu config for virgo_menu.py
├── mock_logs.txt             # Sample log data for demo/testing
├── scaffolds/                # Project scaffold definitions (JSON)
│   ├── fastapi-crud.json     # FastAPI CRUD API with SQLAlchemy
│   ├── cli-app.json          # Python CLI app with argparse
│   ├── flask-app.json        # Flask web app with Jinja2 templates
│   ├── python-lib.json       # Reusable Python library
│   └── agent-tool.json       # New virgo_*.py framework module
├── Dockerfile                # Container image for web dashboard
├── completions/              # Shell completion scripts
│   ├── virgo.bash            #   Bash (subcommands + flags + dynamic scaffold data)
│   ├── virgo.zsh             #   Zsh (compdef-based, same coverage)
│   └── virgo.ps1             #   PowerShell (Register-ArgumentCompleter)
├── pyproject.toml
├── pytest.ini                # pytest config
├── mypy.ini                  # mypy config (strict, ignore missing imports)
├── requirements.txt          # All dependencies for pip install
├── .env.example              # Environment variable template
├── data/
│   ├── sample_network_map.json       # Mock network scan data (demo/testing)
│   ├── sample_diagnostics_report.json # Mock diagnostic report (demo/testing)
│   └── sample_candidate_profile.txt   # Sample profile text (demo/testing)
├── tests/
│   ├── test__console.py            # 4 tests for _console.py icon helper
│   ├── test_autodepend.py          # 12 tests for autodepend (import extraction, classification, auto-install)
│   ├── test_critic.py              # 16 tests for critic (AST checks, line checks, file review)
│   ├── test_environment.py         # 18 tests for AgentEnvironment (setup/teardown, packages, script execution)
│   ├── test_fingerprinter.py       # 3 tests for virgo_fingerprinter (TCP banner grab)
│   ├── test_memory.py              # 11 tests for memory (save/load, list sessions, JSON encoder)
│   ├── test_orchestrator_pytest.py # 26 tests for orchestrator (state, discovery, run smoke tests)
│   ├── test_sandbox.py            # 11 tests for virgo_sandbox (command validation + execution)
│   ├── test_scaffold.py           # 25 tests for scaffold (list/load/generate, syntax validation, edge cases)
│   ├── test_tools.py              # 23 tests for tools (ToolRegistry, file_sampler, code_patcher, git, python_runner)
│   ├── test_webhook.py            # 5 tests for virgo_webhook (telemetry + dispatch)
│   └── __init__.py
├── .github/workflows/
│   └── test.yml              # CI: 3 OS × 3 Python versions, pytest + mypy
├── README.md
├── AGENTS.md
└── .gitignore
```

## Essential commands

```bash
# ── Build & Install ──
pip install -e .                          # Editable install (dev mode)
pip install -e .[dev]                     # With dev deps (pytest, mypy)
python -m build                           # Build wheel + sdist (install build first)
pip install dist/virgo_agent-*.whl        # Install from wheel

# ── Scaffold (generate project skeletons) ──
virgo scaffold                            # List available scaffolds
virgo scaffold fastapi-crud               # Show scaffold details
virgo scaffold fastapi-crud --output ./myapi --var project_name=myapi   # Generate project
virgo scaffold cli-app -o ./mycli -v project_name=mycli -v app_description="A CLI tool"

# ── Run pipeline ──
python cli.py run --goal "parse mock_logs.txt"
# or: virgo run --goal "parse mock_logs.txt"

# Run with LLM-backed policies (requires Ollama):
python cli.py run --llm --goal "build a web scraper"

# Launch web dashboard:
python cli.py serve
# or: virgo serve

# List saved sessions:
virgo list

# Replay a session:
virgo replay <session-name>

# Show feedback memory:
virgo feedback

# Export session:
virgo export <session-name>

# TUI dashboard:
python virgo_menu.py
# or: virgo-dashboard

# New tools (infrastructure pass):
python virgo_fingerprinter.py     # TCP banner grab (connects to localhost:11434)
python virgo_webhook.py           # Build telemetry JSON, dispatch via print or HTTP POST
python virgo_sandbox.py           # Restricted command sandbox (blocklist-based)
python virgo_watchdog.py          # Run diagnostics→alerts→fixer on a configurable timer

# Demo mode (runs deterministic pipeline):
python cli.py demo --goal "parse mock_logs.txt"

# Testing:
python -m pytest tests/ -v                      # Run all 162 tests
python -m pytest tests/test_environment.py -v   # Environment tests only
python -m pytest tests/ --cov=. --cov-report=term-missing  # With coverage

# Lint:
mypy cli.py orchestrator.py tools.py environment.py --ignore-missing-imports

# Environment:
cp .env.example .env        # Configure env vars (edit as needed)
python -c "from _log import log; log.info('ready')"  # Verify logging

# Individual tools:
python virgo_network_scanner.py
python virgo_diagnostics.py
python virgo_alerts.py
python virgo_fixer.py
python virgo_web_search.py 1   # DuckDuckGo
python virgo_web_search.py 2   # Google
python virgo_web_search.py 3   # YouTube
```

## Architecture & data flow

### Pipeline mode

```
cli.py run --goal "..."
    │
    ▼
environment.setup()          ← creates agent_env/ venv
    │
    ▼
ToolRegistry defaults        ← registers file_sampler, code_patcher, etc.
    │
    ▼
Orchestrator.run(goal, ...)
    │
    ├── Phase 1: DISCOVER
    │   └── walk workspace, sample files (CSV/JSON/txt schemas)
    │
    ├── Phase 2: PLAN
    │   └── planner(goal, state) → plan string
    │       • deterministic: run.py's planner
    │       • LLM-backed: main.py's my_planner (calls Ollama)
    │       • user-provided: any Callable
    │
    ├── Phase 3: GENERATE
    │   └── code_gen(plan, state, registry, env) → [(path, content)]
    │       • deterministic: run.py's code_generator (hard-coded parser)
    │       • LLM-backed: main.py's my_generator (Qwen2.5 Coder)
    │
    └── Phase 4: WTF LOOP (Write → Test → Fix)
        └── for i in range(max_iterations):
            ├── code_patcher tool writes files
            ├── python_runner tool tests each generated file
            ├── critic runs AST checks (optional, --critic flag)
            ├── autodepend installs missing packages (optional)
            └── fixer(error, state) → patches or None
                • deterministic: run.py's fixer (regex-based)
                • LLM-backed: main.py's my_fixer
```

### Dashboard mode

```
virgo_menu.py
    │
    ├── [1]  → virgo_network_scanner.py  (subnet scan → virgo_network_map.json)
    ├── [2]  → virgo_diagnostics.py      (port check + health + log analysis → virgo_full_report.json)
    ├── [3]  → virgo_alerts.py           (evaluates both JSON reports → ALERTS_TRIGGERED.txt)
    ├── [4]  → virgo_fixer.py            (reads ALERTS_TRIGGERED.txt, patches mock_logs.txt)
    ├── [5]  → workflow_check.py         (Ollama port check + file existence)
    ├── [6-8] → virgo_web_search.py      (search engine, results to virgo_search_memory_*.json)
    ├── [9]  → cli.py run                (launches pipeline)
    ├── [10-12] → view files             (read output JSON/TXT)
    ├── [13] → virgo_fingerprinter.py    (TCP banner grab → Ollama headers)
    ├── [14] → virgo_webhook.py          (telemetry → ALERTS_TRIGGERED.txt or HTTP POST)
    ├── [15] → virgo_sandbox.py          (restricted command execution)
    └── [16] → virgo_watchdog.py         (scheduled diag→alerts→fixer runner)
```

The data chain flows through JSON files:
```
virgo_network_scanner → virgo_network_map.json → virgo_alerts → ALERTS_TRIGGERED.txt → virgo_fixer
virgo_diagnostics     → virgo_full_report.json → virgo_alerts ─┘
```

## LLM integration (main.py)

`main.py` provides three policies that talk to any OpenAI-compatible API
(Ollama, vLLM, LM Studio) via stdlib `urllib` — no `openai` package.

| Policy | Default model | Purpose |
|--------|--------------|---------|
| `my_planner` | `qwen2.5-coder:7b` | Analyses discovered files, produces build plan |
| `my_generator` | `qwen2.5-coder:7b` | Generates Python code from plan |
| `my_fixer` | `qwen2.5-coder:7b` | Analyses test failures, produces patches |

Config via env vars: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_TIMEOUT`,
`MODEL_PLANNER`, `MODEL_GENERATOR`, `MODEL_FIXER`.

## Key gotchas & non-obvious patterns

### Windows emoji encoding
Many virgo modules use emoji in print statements. On Windows terminals
with cp1252 encoding, emoji crash with `UnicodeEncodeError`.

**Fix applied**: `_console.py` provides an `icon()` function with automatic
ASCII fallback. All virgo_*.py modules now use `icon('name')` instead of
raw emoji. The `orchestrator._step()` function has its own built-in fallback.

**If adding new print statements**: use `_console.icon()` or add a new
entry to the `_ICONS` dict with both emoji and ASCII versions.

### Script paths in menu
`virgo_menu.py`'s `run_script()` uses `os.path.join(HERE, script_name)`
to resolve script paths. This ensures the dashboard works from any working
directory.

### Pipeline environment isolation
The `Orchestrator.run()` creates an `agent_env/` virtualenv for each run.
Policies that need to install packages should use `env.install()` or
rely on `auto_depend=True`. The environment is torn down after each run.

### Session persistence
Every pipeline run is saved to `.virgo_memory/<name>.json`. Sessions can
be listed, replayed, or exported. The replay feature skips the discovery
phase and re-runs generation + WTF loop with optional new policies.

### Config files
Pipeline configuration can be loaded from JSON/YAML files via
`virgo run --config pipeline.json`. CLI flags override config file values.
YAML requires `pyyaml` (optional, not in pyproject.toml).

### Tool registry pattern
Tools are registered via `ToolRegistry` and looked up by name string.
The orchestrator and policies both interact with tools through this
registry, enabling consistent logging and future tool-approval hooks.

### Critic checks
The `critic.py` module runs AST analysis before the WTF loop. It catches:
- Missing `if __name__ == '__main__'` guard
- Bare `except:` clauses
- `eval()` / `exec()` calls
- Lines over 100 characters
- `import *`
- Missing function docstrings

### Auto-dependency resolution
`autodepend.py` has a hardcoded `_KNOWN_THIRD_PARTY` dict mapping import
names to pip package names. When `auto_depend=True`, the orchestrator
scans generated files for imports and auto-installs any missing packages.

### Plugin system
`plugins.py` scans for `*_plugin.py` files in the framework directory
and calls their `register(registry)` function. Simple extension mechanism.

### Mock data
`mock_logs.txt` is a sample log file used by the demo pipeline and
diagnostics modules. The deterministic policies in `run.py` are designed
to parse this file specifically.

## Testing

### pytest suite (162 tests)

```bash
python -m pytest tests/ -v
```

| Test file | Tests | What it covers |
|-----------|-------|----------------|
| `tests/test__console.py` | 4 | `icon()` known keys, unknown keys, ASCII fallback, emoji mode |
| `tests/test_autodepend.py` | 12 | Import extraction, classification, third-party detection, auto-install |
| `tests/test_critic.py` | 16 | AST checks (main guard, bare except, eval/exec, import star, docstrings), line checks (long lines, secrets), file review |
| `tests/test_environment.py` | 18 | AgentEnvironment construction, setup/teardown/recreate, package install/ensure, script/file execution, edge cases |
| `tests/test_fingerprinter.py` | 3 | TCP connection refused, banner receive, socket timeout |
| `tests/test_memory.py` | 11 | Save/load with names/paths/auto-names, list sessions sorting, JSON encoder for Path |
| `tests/test_orchestrator_pytest.py` | 26 | Dataclasses (WorkspaceState, DiscoveredFile, GeneratedFile, TestLog), step printer, Orchestrator construction/is_excluded/discover/run smoke tests |
| `tests/test_sandbox.py` | 11 | Safe commands (ipconfig, systeminfo, ping), forbidden commands (rmdir, del, shutdown, -s, -rf), empty input, all-forbidden coverage list, `run_sandboxed()` execution |
| `tests/test_scaffold.py` | 25 | Scaffold list/load/generate, template substitution, all 5 scaffolds, output structure, syntax validation, edge cases |
| `tests/test_tools.py` | 23 | Tool/ToolRegistry CRUD, file_sampler (CSV/JSON/txt/nonexistent), code_patcher (write/patch/not-found), port check, git_tool, python_runner |
| `tests/test_webhook.py` | 5 | `build_telemetry()` missing file, empty file, with alerts; `dispatch_webhook()` idle (no file), dispatched (file present) |

### Smoke tests (no test framework needed — legacy)

```bash
# Core environment + tools:
python test_modules.py

# Orchestrator WTF loop:
python test_orchestrator.py

# Critic + auto-depend integration:
python test_critic_depend.py
```

## Dependencies

| Package | Required for | Optional? |
|---------|-------------|-----------|
| (stdlib only) | Core pipeline, all virgo_*.py | No |
| requests | Webhook HTTP POST | Yes |
| rich | CLI formatting enhancements | Yes |
| fastapi | Web dashboard (`virgo serve`) | Yes |
| uvicorn | Web dashboard | Yes |
| jinja2 | Web dashboard templates | Yes |
| pyyaml | YAML config files | Yes |
| python-dotenv | .env loading in cli.py | Yes |
| pytest | Test suite | Yes (dev) |
| pytest-cov | Coverage reports | Yes (dev) |
| mypy | Static type checking | Yes (dev) |

## Infrastructure notes

### Build system
- Backend: `setuptools.build_meta` (via `pyproject.toml`)
- Module discovery: explicit `py_modules` list in `setup.py` (flat layout — all `.py` files at root level)
- Entry points: `virgo` → `cli:main`, `virgo-dashboard` → `virgo_menu:master_dashboard`
- Optional deps: `web` (fastapi, uvicorn, jinja2), `yaml` (pyyaml), `dev` (pytest, pytest-cov, mypy)
- Source distribution excludes `agent_env/`, `tests/`, `data/`, `.github/` (via `MANIFEST.in`)
- `__init__.py` at root is a doc-only package marker; modules are installed as top-level flat modules
- Build artifacts land in `dist/`; add to `.gitignore`

### CI workflow (`.github/workflows/test.yml`)
- Matrix: ubuntu-latest, windows-latest × Python 3.11, 3.12, 3.13
- Steps: install deps → mypy lint (continue-on-error) → pytest with coverage → smoke-test imports
- Test step runs `--cov=. --cov-report=term-missing` to report per-module coverage
- Coverage is still relatively low; core-pipeline modules (orchestrator, tools, environment, memory, critic, autodepend) now have 90+ new tests but legacy virgo_*.py scripts remain untested

### Docker (`Dockerfile`)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install .[web]
EXPOSE 8765
CMD ["virgo", "serve", "--host", "0.0.0.0", "--port", "8765"]
```

Build and run:

```bash
docker build -t virgo-agent .
docker run -p 8765:8765 virgo-agent
```

The image uses `python:3.12-slim`, copies source files directly (no wheel build step), installs with `[web]` extras for FastAPI/Uvicorn/Jinja2, and exposes the web dashboard on port 8765.

### Shell completions

Completion scripts live in `completions/` and are printed to stdout via `virgo completion <shell>`:

```bash
virgo completion bash   # source this in .bashrc
virgo completion zsh    # compdef-based
virgo completion powershell   # Register-ArgumentCompleter
```

| Shell | File | Mechanism |
|-------|------|-----------|
| Bash | `completions/virgo.bash` | Dynamic scaffold name/variable lookup via embedded Python helper functions |
| Zsh | `completions/virgo.zsh` | `compdef` with subcommand, flag, scaffold-name, and template-variable completions |
| PowerShell | `completions/virgo.ps1` | `Register-ArgumentCompleter` with Python helper for scaffold data |

All three scripts complete: subcommands (`run`, `serve`, `list`, `replay`, `export`, `feedback`, `demo`, `completion`, `scaffold`), flags (`--goal`, `--llm`, `--model`, `--critic`, `--auto-approve`, `--max-iterations`, `--config`, `--output`, `--var`, `--install`, `--uninstall`), and dynamic scaffold names with their template variables.

The `virgo completion` CLI subcommand reads the script file from `completions/` and writes it to stdout — no dynamic generation, suitable for offline use.

### Logging (`_log.py`)
- Singleton `log` via `logging.getLogger('virgo')`
- Reads `VIRGO_LOG_LEVEL` (default: WARNING) and `VIRGO_LOG_FILE` (optional) env vars
- New modules (`virgo_webhook.py`, `virgo_watchdog.py`, `virgo_fingerprinter.py`, `virgo_sandbox.py`) use `_log`
- Older virgo_*.py scripts still use `print()` for interactive CLI output

### Webhook HTTP POST (`virgo_webhook.py`)
- `WEBHOOK_URL` env var controls mode: empty = simulation (print JSON), set = real HTTP POST
- `dispatch_http()` uses `urllib.request` with retry + linear backoff (3 retries, 1s delay)
- Payload: JSON with `agent`, `timestamp`, `alerts` fields

### Watchdog (`virgo_watchdog.py`)
- `run_cycle()` launches `virgo_diagnostics.py` → `virgo_alerts.py` → `virgo_fixer.py` as subprocesses
- `run_watchdog()` main loop runs N cycles with configurable interval (`WATCHDOG_INTERVAL` env var, default 30s)
- Process isolation: each tool runs independently; errors in one don't block the others

### Dashboard config (`dashboard.json`)
- Loaded at import time in `virgo_menu.py` into `MENU_CONFIG` dict
- Each entry has `id`, `title`, `script`, `args`, `category` fields
- Menu rendering still hard-codes visual layout but dispatches using config entries

### Mock data (`data/`)
- `sample_network_map.json` — realistic mock network scan with 5 devices (router, web, db, IoT, printer)
- `sample_diagnostics_report.json` — realistic mock diagnostic with warnings + critical findings
- `sample_candidate_profile.txt` — sample profile text for pipeline demo
- Used by `cli.py demo` and manual testing of the data chain

### Environment variables (`.env.example`)
| Variable | Default | Purpose |
|----------|---------|---------|
| `VIRGO_LOG_LEVEL` | WARNING | Logging threshold (DEBUG, INFO, WARNING, ERROR) |
| `VIRGO_LOG_FILE` | (stderr) | Log file path |
| `WEBHOOK_URL` | (empty) | Webhook POST target; empty = simulation |
| `WATCHDOG_INTERVAL` | 30 | Seconds between watchdog cycles |
| `WATCHDOG_CYCLES` | 5 | Number of watchdog cycles before exit |
| `LLM_BASE_URL` | — | Ollama server URL |
| `LLM_API_KEY` | — | API key for non-Ollama endpoints |
| `MODEL_PLANNER` | — | Planner model override |
| `MODEL_GENERATOR` | — | Generator model override |
| `MODEL_FIXER` | — | Fixer model override |

## Scaffold system

### Available scaffolds (5 built-in + plugin packages)

| Name | Description | Dependencies | Files | Source |
|------|-------------|-------------|-------|--------|
| `fastapi-crud` | FastAPI CRUD API with SQLAlchemy + SQLite | fastapi, uvicorn, sqlalchemy, pydantic | 11 | built-in |
| `cli-app` | Python CLI app with argparse + entry-point | (none) | 8 | built-in |
| `flask-app` | Flask web app with Jinja2 templates + static files | flask, jinja2 | 7 | built-in |
| `python-lib` | Reusable library with pyproject.toml + tests | (none) | 8 | built-in |
| `agent-tool` | New virgo_*.py module following framework conventions | (none) | 2 | built-in |

### How it works

1. Scaffold definitions live in `scaffolds/*.json` — each specifies files, template variables, dependencies
2. `virgo_scaffold.py` reads a scaffold, renders `{{var}}` placeholders, writes all files to the output directory
3. Built-in variable `{{stars}}` auto-computes a `***` line matching `project_name` length (no extra prompts needed)
4. Scafs can be extended by adding new `.json` files to `scaffolds/` — no code changes needed
5. Entry points: `virgo scaffold list`, `virgo scaffold <name>`, `virgo scaffold <name> --output <dir> --var key=value`
6. Dashboard menus [17]-[22] in `virgo_menu.py` expose all scaffolds with project-name prompts

### Plugin scaffolds (installed via pip)

Third-party packages can contribute scaffolds dynamically using one of two mechanisms:

1. **`scaffolds/*.json` directory**: Any installed package containing a `scaffolds/` directory with `.json` files is auto-discovered via `importlib.metadata`
2. **`virgo_scaffolds` entry points**: Packages can register an `entry_points` group `virgo_scaffolds` that returns a scaffold dict

Plugin scaffolds appear alongside built-in scaffolds in `virgo scaffold list` with the `_source` field set to the package name.

```bash
virgo scaffold install <package>    # pip install + verify scaffolds found
virgo scaffold uninstall <package>  # pip uninstall -y
virgo scaffold list                 # shows built-in + plugin scaffolds
```

The `--install` and `--uninstall` flags dispatch to `install_scaffold()` / `uninstall_scaffold()` in `virgo_scaffold.py`, which handle pip operations and verification.

### Creating a new scaffold

Drop a JSON file into `scaffolds/`:

```json
{
  "name": "my-scaffold",
  "version": "0.1.0",
  "description": "Description shown in lists",
  "dependencies": ["some-package"],
  "prompts": { "project_name": "default_name" },
  "files": {
    "README.md": "# {{project_name}}\n",
    "{{project_name}}/__init__.py": "# {{project_name}} v{{version}}\n"
  }
}
```

Variables are substituted in both file paths and content. Any variable not provided via `--var` falls back to the `prompts` default, or to the key name itself.

## Naming conventions

- Files: `snake_case.py`
- Modules: lowercase, descriptive — `orchestrator`, `environment`, `tools`
- CLI tools: `virgo_<purpose>.py` — `virgo_network_scanner`, `virgo_web_search`,
|  `virgo_fingerprinter`, `virgo_webhook`, `virgo_sandbox`, `virgo_watchdog`
- Classes: `PascalCase` — `Orchestrator`, `AgentEnvironment`, `ToolRegistry`
- Functions: `snake_case` — `run_subnet_scan`, `auto_remediate`, `check_thresholds`
- Constants: `UPPER_SNAKE_CASE` — except for the `_ICONS` and `_KNOWN_THIRD_PARTY` dicts
- Private: `_prefix` — `_supports_emoji()`, `_check()`, `_step()`
- All new code uses `from __future__ import annotations`
