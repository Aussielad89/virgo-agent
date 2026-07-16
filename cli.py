#!/usr/bin/env python3
"""
cli — unified entry point for virgo.

Usage::

    virgo                                    # launch TUI dashboard
    virgo run --goal "parse logs"            # run pipeline
    virgo chat                               # interactive chat with file upload
    virgo chat --resume <session>            # resume a saved chat
    virgo serve                               # launch web dashboard
    virgo replay <session>                    # replay a saved run
    virgo list                                # list saved sessions
    virgo feedback                            # show feedback memory
    virgo version                             # show version
    virgo update                              # pull latest from git
    virgo doctor                              # run health checks

Chat commands: /upload <file>, /save, /history, /help, /clear
"""

from __future__ import annotations

import argparse
import os
import sys
import subprocess
from pathlib import Path

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

VERSION = "0.5.0"

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from logo import print_logo

try:
    from _console import icon
except Exception:  # pragma: no cover
    def icon(name: str) -> str:  # type: ignore
        return ""


def cmd_run(args: argparse.Namespace) -> None:
    """Run the pipeline with optional LLM policies."""
    print_logo()

    # Load config file if provided
    if args.config:
        try:
            from config import load
            cfg = load(args.config)
            # Merge CLI overrides
            for key, val in vars(args).items():
                if val is not None and key in cfg:
                    cfg[key] = val
            goal = cfg.get("goal", args.goal)
            max_iterations = cfg.get("max_iterations", args.iterations)
            run_critic = cfg.get("critic", args.critic)
            auto_depend = cfg.get("auto_depend", args.auto_depend)
            use_llm = cfg.get("llm", args.llm)
            name = cfg.get("name", args.name)
            excludes = cfg.get("workspace_excludes", None)
        except Exception as exc:
            print(f"[virgo] Config error: {exc}")
            sys.exit(1)
    else:
        goal = args.goal
        max_iterations = args.iterations
        run_critic = args.critic
        auto_depend = args.auto_depend
        use_llm = args.llm
        name = args.name
        excludes = None

    from environment import AgentEnvironment
    from tools import ToolRegistry
    from orchestrator import Orchestrator

    env = AgentEnvironment(base_path=str(HERE))
    if env.is_ready:
        env.teardown()
    env.setup()

    reg_kwargs = {}
    if excludes:
        reg_kwargs["workspace_excludes"] = excludes

    registry = ToolRegistry()
    registry.register_defaults(env)

    # Auto-load plugins
    from plugins import load_all
    load_all(registry)

    orch = Orchestrator(
        env, registry, base_path=str(HERE),
        workspace_excludes=excludes or [
            "agent_env",
            ".crush",
            ".git",
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
            ".virgo_memory",
            ".coverage",
            "dist",
            "virgo_agent.egg-info",
            ".github",
            "completions",
            "scaffolds",
            "data",
            "tests",
            ".env",
            ".env.example",
            "mock_logs.txt",
            "logo.svg",
            "dashboard.json",
            "out.py",
            "__init__.py",
            "output",
        ],
    )

    # Optional LLM policies
    planner = code_gen = fixer = None
    if use_llm:
        try:
            import main
            # Router config — file overrides env
            if hasattr(args, "router") and args.router:
                main.ROUTER_CONFIG = main.router_from_file(args.router)
            # --crush flag is a fallback when no per-role router config
            if args.crush:
                if not main.ROUTER_CONFIG:
                    main.USE_CRUSH = True
            # Default: stream output when attached to a TTY (instant feedback).
            if getattr(args, "no_stream", False):
                main.STREAM_OUTPUT = False
            elif getattr(args, "stream", False):
                main.STREAM_OUTPUT = True
            elif sys.__stdout__.isatty():
                main.STREAM_OUTPUT = True
            if getattr(args, "fast", False):
                main.FAST_MODE = True
            if hasattr(args, 'fallback_model') and args.fallback_model:
                main.FALLBACK_MODEL = args.fallback_model
            planner = main.my_planner
            # Select generator based on --lang
            if args.lang == "py":
                code_gen = main.my_generator
            else:
                from generators import get_generator
                gen = get_generator(args.lang)

                def code_gen(plan, state, registry, env):
                    return gen.generate(plan)
            fixer = main.my_fixer
        except ImportError as exc:
            print(f"[virgo] Could not load LLM policies: {exc}")

    state = orch.run(
        goal=goal,
        planner=planner,
        code_gen=code_gen,
        fixer=fixer,
        max_iterations=max_iterations,
        run_critic=run_critic,
        auto_depend=auto_depend,
        auto_approve=args.yes if hasattr(args, 'yes') else False,
    )

    # Save state
    try:
        from memory import save_state
        path = save_state(state, name=name)
        print(f"\n  [virgo] Session saved: {path}")
    except Exception as exc:
        print(f"\n  [virgo] Save skipped: {exc}")

    # Show result
    print(f"\n  {'=' * 60}")
    print(f"  Result:  {'PASS' if state.loop_passed else 'FAIL'}")
    print(f"  Files:   {len(state.generated_files)}  |  "
          f"Iterations: {state.iteration}")
    if state.generated_files:
        for gf in state.generated_files:
            mark = "PASS" if gf.passed else "FAIL"
            print(f"    {gf.path:30s}  [{mark}]")
    print(f"  {'=' * 60}")

    env.teardown()

    # -- Git integration ---------------------------------------------------
    if state.loop_passed and (args.git or args.git_push or args.git_branch):
        from virgo_git import git_commit, git_branch as _git_branch

        push = args.git_push
        branch = args.git_branch

        if branch:
            _git_branch(branch)

        msg = f"[virgo] Pipeline: {goal}"
        git_commit(message=msg, push=push)

    sys.exit(0 if state.loop_passed else 1)


def cmd_serve(args: argparse.Namespace) -> None:
    """Launch the web dashboard."""
    from server import serve
    serve(host=args.host, port=args.port)


def cmd_list(args: argparse.Namespace) -> None:
    """List saved sessions."""
    from memory import list_sessions
    sessions = list_sessions()
    if not sessions:
        print("[virgo] No saved sessions.")
        return
    print(f"\n  {'Name':30s}  {'Goal':45s}  {'Status':10s}  {'Files':6s}")
    print(f"  {'-'*30}  {'-'*45}  {'-'*10}  {'-'*6}")
    for s in sessions:
        status = "PASS" if s.get("loop_passed") else ("FAIL" if s.get("loop_passed") is False else "---")
        goal = s.get("goal", "")[:44]
        print(f"  {s['name']:30s}  {goal:45s}  {status:10s}  {s.get('generated', 0):6d}")
    print()


def cmd_replay(args: argparse.Namespace) -> None:
    """Replay a saved session."""
    from environment import AgentEnvironment
    from tools import ToolRegistry
    from orchestrator import Orchestrator
    from memory import replay as replay_fn, load_state

    # Quick check the session exists
    load_state(args.session)

    env = AgentEnvironment(base_path=str(HERE))
    if env.is_ready:
        env.teardown()
    env.setup()

    registry = ToolRegistry()
    registry.register_defaults(env)

    orch = Orchestrator(
        env, registry, base_path=str(HERE),
        workspace_excludes=["agent_env", ".crush", ".git", "__pycache__", ".mypy_cache"],
    )

    print(f"\n  [virgo] Replaying: {args.session}")

    # Optional LLM policies for gen/fix
    code_gen = fixer = None
    if args.llm:
        try:
            from main import my_generator, my_fixer
            code_gen = my_generator
            fixer = my_fixer
        except ImportError:
            pass

    state = replay_fn(
        args.session, orch, env, registry,
        code_gen=code_gen,
        fixer=fixer,
        max_iterations=args.iterations,
    )

    print(f"\n  Result: {'PASS' if state.loop_passed else 'FAIL'}")
    env.teardown()
    sys.exit(0 if state.loop_passed else 1)


def cmd_demo(args: argparse.Namespace) -> None:
    """Run the deterministic demo pipeline (no LLM required)."""
    from run import main as run_main
    run_main(goal=getattr(args, "goal", None))


def cmd_version(_args: argparse.Namespace) -> None:
    """Show version information."""
    print(f"virgo-agent v{VERSION}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Path:   {HERE}")


def cmd_menu(_args: argparse.Namespace) -> None:
    """Launch the TUI master dashboard."""
    from virgo_menu import master_dashboard
    master_dashboard()


def cmd_update(_args: argparse.Namespace) -> None:
    """Pull the latest version from git."""
    HERE = Path(__file__).resolve().parent
    if not (HERE / ".git").is_dir():
        print("[virgo] Not a git repository — cannot update.")
        sys.exit(1)
    print("[virgo] Pulling latest changes...")
    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=str(HERE),
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        sys.exit(1)
    print("[virgo] Update complete.")


def cmd_doctor(_args: argparse.Namespace) -> None:
    """Run environment health checks."""
    import shutil
    import urllib.request as _ur
    import json as _json
    here = Path(__file__).resolve().parent

    ok_count = 0
    total = 0

    def check(name: str, fn: callable) -> None:
        nonlocal ok_count, total
        total += 1
        try:
            ok = fn()
        except Exception:
            ok = False
        if ok:
            ok_count += 1
        status = f"[{'OK' if ok else 'MISS'}]"
        print(f"  {status}  {name}")

    # ── File & project checks ──
    check("Repository (.git)", lambda: (here / ".git").is_dir())
    check("Python 3.11+", lambda: sys.version_info >= (3, 11))
    check("Dashboard config", lambda: (here / "dashboard.json").exists())
    check("Mock logs", lambda: (here / "mock_logs.txt").exists())
    check("virgo.bat wrapper", lambda: (here / "virgo.bat").exists())

    # ── LLM / Ollama ──
    def check_llm() -> bool:
        url = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
        req = _ur.Request(f"{url.rstrip('/')}/models", method="GET")
        try:
            with _ur.urlopen(req, timeout=5) as resp:
                data = _json.loads(resp.read())
                return "models" in data or "data" in data
        except Exception:
            return False
    check("LLM reachable (Ollama)", check_llm)

    # ── Git status ──
    def check_git_clean() -> bool:
        r = subprocess.run(["git", "status", "--porcelain"],
                           cwd=here, capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and r.stdout.strip() == ""
    check("Git working tree clean", check_git_clean)

    # ── Disk space ──
    def check_disk() -> bool:
        usage = shutil.disk_usage(here)
        free_gb = usage.free / (1024 ** 3)
        return free_gb > 1.0
    check("Disk space (>1 GB free)", check_disk)

    # ── Dependencies ──
    def check_deps() -> bool:
        required = {"pytest", "requests", "fastapi", "uvicorn", "jinja2", "pyyaml"}
        r = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=freeze"],
            capture_output=True, text=True, timeout=30,
        )
        installed = {line.split("==")[0].lower() for line in r.stdout.splitlines() if "==" in line}
        missing = required - installed
        return len(missing) <= 2  # allow a few optional deps missing
    check("Core dependencies installed", check_deps)

    print(f"\n  {ok_count}/{total} checks passed  |  virgo-agent v{VERSION}")


def cmd_config(args: argparse.Namespace) -> None:
    """View or set virgo configuration (environment variables)."""

    config_vars = {
        "LLM_BASE_URL": "http://localhost:11434/v1",
        "LLM_API_KEY": "sk-no-key-required",
        "LLM_TIMEOUT": "300",
        "MODEL_PLANNER": "qwen2.5-coder:7b",
        "MODEL_GENERATOR": "qwen2.5-coder:7b",
        "MODEL_FIXER": "qwen2.5-coder:7b",
        "FALLBACK_MODEL": "",
        "VIRGO_LOG_LEVEL": "WARNING",
        "VIRGO_LOG_FILE": "",
        "WEBHOOK_URL": "",
        "WATCHDOG_INTERVAL": "30",
        "WATCHDOG_CYCLES": "5",
    }

    dotenv_path = HERE / ".env"

    # --get <key>
    if args.get:
        key = args.get.upper()
        val = os.environ.get(key, config_vars.get(key, "(not set)"))
        print(f"{key}={val}")
        return

    # --set key=value
    if args.set:
        if "=" not in args.set:
            print("[virgo] Use --set KEY=VALUE")
            return
        key, _, val = args.set.partition("=")
        key = key.upper().strip()
        val = val.strip()
        # Update in current process
        os.environ[key] = val
        # Persist to .env
        lines = []
        if dotenv_path.exists():
            lines = dotenv_path.read_text(encoding="utf-8").splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"export {key}="):
                lines[i] = f"{key}={val}"
                found = True
                break
        if not found:
            lines.append(f"{key}={val}")
        dotenv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[virgo] {key}={val}  (saved to .env)")
        return

    # --unset <key>
    if args.unset:
        key = args.unset.upper()
        os.environ.pop(key, None)
        if dotenv_path.exists():
            lines = [line for line in dotenv_path.read_text(encoding="utf-8").splitlines()
                     if not line.strip().startswith(f"{key}=") and not line.strip().startswith(f"export {key}=")]
            dotenv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[virgo] {key} removed")
        return

    # Default: show all
    print(f"\n  virgo configuration ({dotenv_path if dotenv_path.exists() else 'env defaults'}):\n")
    for key, default in sorted(config_vars.items()):
        val = os.environ.get(key, default)
        marker = " *" if os.environ.get(key) else ""
        print(f"    {key:25s} = {val}{marker}")
    print("\n  * = overridden in current environment")
    print("  Use:  virgo config --set KEY=VALUE")
    print("        virgo config --get KEY")
    print("        virgo config --unset KEY\n")


def cmd_self_install(_args: argparse.Namespace) -> None:
    """Add virgo to the system PATH for access from any terminal."""
    import subprocess as _subprocess
    here = Path(__file__).resolve().parent
    bat = here / "virgo.bat"

    if not bat.exists():
        print(f"[virgo] {bat} not found — nothing to install.")
        return

    # Check current PATH
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if str(here) in path_dirs:
        print(f"[virgo] {here} is already in PATH.")
        return

    # Add to user PATH via setx (Windows) or .profile suggestion
    if sys.platform == "win32":
        try:
            result = _subprocess.run(
                ["setx", "PATH", f"{here};%PATH%"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                print(f"[virgo] Added {here} to user PATH.")
                print("  Restart your terminal or run:  refreshenv")
            else:
                print(f"[virgo] setx failed: {result.stderr}")
                print(f"  Manually add this folder to your PATH:\n    {here}")
        except FileNotFoundError:
            print("[virgo] setx not found. Add this to PATH manually:")
            print(f"    {here}")
    else:
        profile = Path.home() / ".profile"
        line = f'\nexport PATH="{here}:$PATH"\n'
        try:
            with open(profile, "a") as f:
                f.write(line)
            print(f"[virgo] Added to {profile}. Run:  source {profile}")
        except Exception as exc:
            print(f"[virgo] Could not write {profile}: {exc}")


def cmd_diff(args: argparse.Namespace) -> None:
    """Compare two saved sessions."""
    from virgo_diff import cmd_diff as _diff
    _diff(args)


def cmd_swarm(args: argparse.Namespace) -> None:
    """Multi-agent delegation — run parallel sub-agents."""
    # Parse agents from CLI args or JSON file
    agents: list[tuple[str, str]] = []
    if args.agent_file:
        import json
        with open(args.agent_file) as f:
            entries = json.load(f)
        for entry in entries:
            agents.append((entry["name"], entry["goal"]))
    elif args.agent:
        for a in args.agent:
            if ":" in a:
                name, _, goal = a.partition(":")
                agents.append((name.strip(), goal.strip()))
            else:
                print(f"[virgo] Invalid agent spec: {a!r} (expected name:goal)")
                sys.exit(1)
    else:
        print("[virgo] No agents specified — use --agent name:goal or --agent-file")
        sys.exit(1)

    from environment import AgentEnvironment
    from tools import ToolRegistry
    from orchestrator import Orchestrator

    HERE = Path(__file__).resolve().parent
    env = AgentEnvironment(base_path=str(HERE))
    if env.is_ready:
        env.teardown()
    env.setup()
    registry = ToolRegistry()
    registry.register_defaults(env)

    from plugins import load_all
    load_all(registry)

    orch = Orchestrator(env, registry, base_path=str(HERE))
    results = orch.swarm(
        goal=args.goal,
        agents=agents,
        max_iterations=args.iterations,
        use_llm=args.llm,
        share=getattr(args, 'share', False),
        ordered=getattr(args, 'ordered', False),
    )

    # Save results
    try:
        from memory import save_state
        from orchestrator import WorkspaceState
        state = WorkspaceState(
            goal=f"swarm: {args.goal}",
            base_path=str(HERE),
        )
        state.context["swarm_results"] = results
        path = save_state(state, name=args.name if hasattr(args, 'name') else None)
        if path:
            print(f"\n[virgo] Swarm saved: {path}")
    except Exception as exc:
        print(f"[virgo] Could not save swarm state: {exc}")

    env.teardown()
    passed = sum(1 for r in results if r["status"] == "success")
    sys.exit(0 if passed == len(results) else 1)


def cmd_watch(args: argparse.Namespace) -> None:
    """Watch a directory and re-run the pipeline on change events."""
    from virgo_watcher import FileWatcher, run_pipeline
    from datetime import datetime, timezone

    watch_dir = Path(args.dir or ".").resolve()

    exclude = ["__pycache__", ".git", ".venv",
               "agent_env", ".virgo_memory", ".coverage",
               "dist", "virgo_agent.egg-info"]
    exclude.extend(args.exclude or [])

    watcher = FileWatcher(
        watch_dir,
        interval=args.interval,
        debounce=args.debounce,
        exclude=exclude,
    )

    def on_change(changed: list[str]) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"\n  [{ts}] Change detected — {len(changed)} file(s)")
        for path in changed[:10]:
            print(f"    📄 {path}")
        if len(changed) > 10:
            print(f"    … and {len(changed) - 10} more")

        run_pipeline(
            args.goal,
            dir_path=str(watch_dir),
            use_llm=bool(args.llm),
            max_iterations=args.iterations,
            router=args.router,
            use_crush=bool(args.crush),
            stream=bool(args.stream),
        )

    if args.llm:
        print("  [watch] LLM mode enabled")
    if args.router:
        print(f"  [watch] Using router: {args.router}")

    watcher.start(on_change)


def cmd_feedback(args: argparse.Namespace) -> None:
    """Show feedback memory contents."""
    from memory import FeedbackMemory
    fb = FeedbackMemory()
    if len(fb) == 0:
        print("[virgo] Feedback memory is empty.")
        return
    print(f"\n  [virgo] Feedback memory: {len(fb)} entries\n")
    for i, entry in enumerate(fb._data[-10:], 1):
        print(f"  {i}. error: {entry['error'][:80]}")
        print(f"     fix:   {entry['new'][:80]}")
        print()


def cmd_templates(args: argparse.Namespace) -> None:
    """List and generate from built-in templates."""
    from templates import list_templates, generate

    if args.generate:
        generate(
            args.generate,
            args.output or f"{args.generate}_output.py",
            name=args.name or args.generate,
            description=args.description or f"Generated {args.generate} script",
            target=args.target or "module",
        )
        print(f"\n  [virgo] Generated: {args.output or f'{args.generate}_output.py'}")
        return

    # List templates
    templates = list_templates()
    print("\n  Available templates:\n")
    for t in templates:
        print(f"    {t['key']:20s}  {t['name']:15s}  {t['description']}")
    print("\n  Use: virgo templates --generate <key> [--output file] [--name Name] [--description '...']\n")


def cmd_export(args: argparse.Namespace) -> None:
    """Export a saved session as HTML or Markdown."""
    from memory import load_state
    from exporter import export_html, export_markdown

    data = load_state(args.session)

    # Reconstruct a minimal state-like object for the exporter
    from orchestrator import WorkspaceState, DiscoveredFile, GeneratedFile, TestLog

    state = WorkspaceState(
        goal=data.get("goal", ""),
        base_path=data.get("base_path", "."),
        plan=data.get("plan", ""),
        phase=data.get("phase", "complete"),
        iteration=data.get("iteration", 0),
        loop_passed=data.get("loop_passed", False),
    )
    for df_dict in data.get("discovered_files", []):
        state.discovered_files.append(DiscoveredFile(**df_dict))
    for gf_dict in data.get("generated_files", []):
        state.generated_files.append(GeneratedFile(**gf_dict))
    for tl_dict in data.get("test_logs", []):
        state.test_logs.append(TestLog(**tl_dict))

    out = args.output or f"{args.session}_report.{args.format}"
    if args.format == "html":
        path = export_html(state, out)
    else:
        path = export_markdown(state, out)

    print(f"\n  [virgo] Exported: {path}\n")


def cmd_plugins(args: argparse.Namespace) -> None:
    """List and load plugins."""
    from plugins import discover, load_all, PLUGIN_DIRS
    from tools import ToolRegistry

    if args.load:
        reg = ToolRegistry()
        count = load_all(reg)
        tools = reg.list()
        print(f"\n  [virgo] Loaded {count} plugin file(s), {len(tools)} tool(s)")
        for t in tools:
            print(f"    → {t['name']}: {t['description'][:80]}")
        print()
        return

    # List available plugin files
    files = discover()
    if not files:
        print("\n  [virgo] No plugins found. Place .py files in:")
        for d in PLUGIN_DIRS:
            print(f"    {d}")
        print("\n  Use: virgo plugins --load to load them\n")
        return

    print("\n  Plugin files found:")
    for f in files:
        size = f.stat().st_size
        print(f"    {f.parent.name}/{f.name}  ({size} B)")
    print("\n  Use: virgo plugins --load to load them\n")


def cmd_completion(args: argparse.Namespace) -> None:
    """Print shell completion script to stdout."""
    shell = args.shell
    here = Path(__file__).parent
    script_path = here / "completions" / f"virgo.{shell}"
    if not script_path.exists():
        print(f"  No completion script for {shell!r}.", file=sys.stderr)
        print("  Supported shells: bash, zsh, powershell", file=sys.stderr)
        sys.exit(1)
    print(script_path.read_text(encoding="utf-8"), end="")


def cmd_testgen(args: argparse.Namespace) -> None:
    """Generate pytest test stubs from Python source files."""
    from virgo_testgen import generate_tests
    from _console import icon

    source = args.path or args.dir
    print(f"\n{icon('test')}  Generating tests from: {source}")
    results = generate_tests(
        path=source,
        output_dir=args.output,
        overwrite=args.overwrite,
    )

    if results:
        print(f"\n  {icon('ok')}  Generated {len(results)} test file(s) in {args.output}/")
        for f in results:
            print(f"     {icon('file')} {f}")
        print()
    else:
        print(f"\n  {icon('info')}  No test files were generated.\n")


def cmd_commit(args: argparse.Namespace) -> None:
    """Stage all changes and commit."""
    from virgo_git import cmd_commit as _cmd_commit
    _cmd_commit(args)


def cmd_doc(args: argparse.Namespace) -> None:
    """Generate API documentation from docstrings."""
    from virgo_docgen import main as docgen_main
    docgen_main([
        "--path", args.path,
        "--output", args.output,
        "--format", args.format,
        "--name", args.name,
    ] + (["--recursive"] if args.recursive else []))


def cmd_agent(args: argparse.Namespace) -> None:
    """Run the autonomous agent runtime (ReAct loop over tools)."""
    import main as _main
    from agent_runtime import AgentConfig, build_runtime

    client = None
    if args.llm:
        try:
            client = _main.get_client_for("agent")
        except Exception as exc:
            print(f"[virgo] LLM client unavailable ({exc}) — running deterministic loop")

    # Streaming default when interactive (same rule as run).
    if args.no_stream:
        _main.STREAM_OUTPUT = False
    elif args.stream or sys.__stdout__.isatty():
        _main.STREAM_OUTPUT = True

    config = AgentConfig(
        max_steps=args.steps,
        max_retries=args.retries,
        use_experience=not args.no_experience,
        mcp_specs=args.mcp or None,
        stream=_main.STREAM_OUTPUT,
    )

    print(f"\n  {icon('rocket')}  Virgo Agent — goal: {args.goal}")
    runtime = build_runtime(client=client, config=config, include_mcp=not args.no_mcp)
    result = runtime.run(args.goal)

    print(f"\n  {'=' * 60}")
    print(f"  Result:  {'PASS' if result.passed else 'FAIL'}")
    print(f"  Steps:   {result.steps}  |  Tools: {', '.join(result.tools_used) or 'none'}")
    if result.evaluation is not None:
        ev = result.evaluation
        print(f"  Score:   {getattr(ev, 'score', 'n/a')}")
        print(f"  Why:     {getattr(ev, 'rationale', '')[:200]}")
    print(f"  {'=' * 60}")
    if result.lessons:
        print("  Lessons learned:")
        for L in result.lessons[:5]:
            print(f"    - {L}")
    # Persist the run transcript for replay/inspection.
    try:
        from memory import save_state  # reuse session persistence if present
        _ = save_state
    except Exception:
        pass
    out_path = HERE / ".virgo_memory" / "last_agent_run.txt"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.transcript, encoding="utf-8")
        print(f"\n  [virgo] Transcript saved: {out_path}")
    except Exception as exc:  # pragma: no cover
        print(f"\n  [virgo] Could not save transcript: {exc}")


def _cmd_chat_upload(history: list[dict[str, str]], arg: str) -> None:
    """Upload a file into the chat context.

    Supports:
      /upload <path>              — single file
      /upload <path1> <path2> ... — multiple files (space-separated)
      /upload *.py                — glob pattern (quoted on most shells)
    """
    import glob as _glob

    if not arg.strip():
        print("  [Usage: /upload <filepath>  or  /upload file1 file2 ...]\n")
        return

    paths: list[Path] = []
    for token in arg.split():
        expanded = list(Path(p) for p in _glob.glob(token) if Path(p).is_file())
        if expanded:
            paths.extend(expanded)
        else:
            p = HERE / token if not Path(token).is_absolute() else Path(token)
            if p.exists() and p.is_file():
                paths.append(p)
            else:
                print(f"  [File not found: {token}]\n")

    if not paths:
        print("  [No valid files found]\n")
        return

    for fp in paths:
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
            ext = fp.suffix.lower()
            lang = {"py": "python", "rs": "rust", "ts": "typescript", "js": "javascript",
                    "json": "json", "yaml": "yaml", "yml": "yaml", "md": "markdown",
                    "toml": "toml", "sh": "bash", "bat": "batch", "ps1": "powershell",
                    "html": "html", "css": "css", "sql": "sql", "txt": "text",
                    "csv": "csv", "xml": "xml"}.get(ext.lstrip("."), "")
            header = f"File: {fp.name} ({len(content)} chars)"
            if len(content) > 50000:
                content = content[:50000] + f"\n... [truncated at 50000 chars, full file is {len(content)} chars]"
            payload = f"{header}\n```{lang}\n{content}\n```"
            history.append({"role": "user", "content": payload})
            print(f"  [Uploaded: {fp.name} ({len(content)} chars)]\n")
        except Exception as exc:
            print(f"  [Error reading {fp.name}: {exc}]\n")


def _cmd_chat_help() -> None:
    print("""
  Virgo Chat Commands:
    /upload <path>    Upload a file into chat context (supports glob, multiple files)
    /save, /s         Save current chat session
    /history          List saved chat sessions
    /help             Show this help
    /clear            Clear chat history
    exit, quit        Exit chat

  Examples:
    /upload log.txt
    /upload src/*.py
    /upload config.json README.md
""")


def cmd_chat(args: argparse.Namespace) -> None:
    """Interactive chat with virgo (backed by LLM if available)."""
    import json as _json
    from datetime import datetime, timezone

    chats_dir = HERE / ".virgo_memory" / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)

    print_logo()
    print("  Virgo Chat - type '/help' for commands, 'exit' to quit\n")

    # Try LLM; fall back to simple echo mode.
    client = None
    try:
        import main
        client = main.get_client_for("agent")
        print("  [LLM connected - responses from local model]\n")
    except Exception:
        print("  [No LLM detected - running in teach/task mode]\n")

    history: list[dict[str, str]] = []

    # Resume from a previous session if --resume was provided
    if args.resume:
        resume_path = chats_dir / args.resume
        if not resume_path.exists():
            resume_path = chats_dir / f"{args.resume}.json"
        if resume_path.exists():
            try:
                data = _json.loads(resume_path.read_text(encoding="utf-8"))
                history = data.get("history", [])
                print(f"  [Resumed chat: {resume_path.name} - {len(history)} messages]\n")
            except Exception as exc:
                print(f"  [Could not resume: {exc}]\n")
        else:
            print(f"  [No saved chat found: {args.resume}]\n")

    session_id = datetime.now(timezone.utc).strftime("chat_%Y%m%d_%H%M%S")

    while True:
        try:
            user_input = input("  >> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
            break
        if user_input.lower() in ("/save", "/s"):
            _save_chat(chats_dir, session_id, history)
            continue
        if user_input.lower() == "/history":
            _list_chats(chats_dir)
            continue
        if user_input.lower() in ("/help", "/?"):
            _cmd_chat_help()
            continue
        if user_input.lower() == "/clear":
            history.clear()
            print("  [Chat history cleared]\n")
            continue
        if user_input.lower().startswith("/upload "):
            _cmd_chat_upload(history, user_input[len("/upload "):])
            continue

        if client:
            history.append({"role": "user", "content": user_input})
            try:
                result = client.chat(history.copy(), temperature=0.7, max_tokens=2048, role="agent")
                if result and result.strip():
                    print(f"  => {result.strip()}\n")
                    history.append({"role": "assistant", "content": result})
                else:
                    print("  [Empty response from LLM]\n")
            except Exception as exc:
                print(f"  [LLM error: {exc}]\n")
                print(f"  => (LLM unavailable) You said: {user_input}\n")
        else:
            print(f"  => You said: {user_input}")
            print("  (Run `virgo run --goal \"...\"` or `virgo doctor` to get started)\n")

    # Auto-save on exit
    if history:
        _save_chat(chats_dir, session_id, history, auto=True)


def _save_chat(chats_dir: Path, session_id: str, history: list[dict[str, str]], auto: bool = False) -> None:
    """Save a chat session to disk."""
    import json as _json
    from datetime import datetime, timezone
    path = chats_dir / f"{session_id}.json"
    data = {
        "session": session_id,
        "saved": datetime.now(timezone.utc).isoformat(),
        "messages": len(history),
        "history": history,
    }
    path.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    label = "Auto-saved" if auto else "Saved"
    print(f"  [{label} chat: {path.name} ({len(history)} messages)]\n")


def _list_chats(chats_dir: Path) -> None:
    """List saved chat sessions."""
    import json as _json
    files = sorted(chats_dir.glob("*.json"), reverse=True)
    if not files:
        print("  [No saved chats]\n")
        return
    print(f"  Saved chats ({len(files)}):\n")
    for f in files[:10]:
        try:
            data = _json.loads(f.read_text(encoding="utf-8"))
            msgs = data.get("messages", "?")
            saved = data.get("saved", "")[:19]
            print(f"    {f.stem:30s}  {msgs:3d} msgs  {saved}")
        except Exception:
            print(f"    {f.stem:30s}  (corrupt)")
    print("  Use:  virgo chat --resume <session_id>\n")


def cmd_scaffold(args: argparse.Namespace) -> None:
    """Generate a project from a scaffold, or list available scaffolds."""
    from virgo_scaffold import list_scaffolds, load_scaffold, generate, install_scaffold, uninstall_scaffold

    if args.install and args.name:
        install_scaffold(args.name)
        return
    if args.uninstall and args.name:
        uninstall_scaffold(args.name)
        return

    if args.name is None:
        # List scaffolds
        scaffolds = list_scaffolds()
        if not scaffolds:
            print("\n  No scaffolds found.\n")
            return
        print(f"\n  Available scaffolds ({len(scaffolds)}):\n")
        for s in scaffolds:
            deps = f"  [{', '.join(s['dependencies'])}]" if s["dependencies"] else ""
            print(f"    {s['name']}{' ' * (24 - len(s['name']))}{s['description']}{deps}")
        print()
        return

    # Show single scaffold details
    if args.name and not args.var and args.output == ".":
        scaffold = load_scaffold(args.name)
        if scaffold:
            print(f"\n  Name:        {scaffold.get('name', '?')}")
            print(f"  Description: {scaffold.get('description', '')}")
            print(f"  Version:     {scaffold.get('version', '0.0.0')}")
            deps = scaffold.get("dependencies", [])
            print(f"  Dependencies: {', '.join(deps) if deps else '(none)'}")
            prompts = scaffold.get("prompts", {})
            if prompts:
                print(f"  Variables:   {', '.join(prompts.keys())}")
            files = scaffold.get("files", {})
            print(f"  Files:       {len(files)}")
            print()
            return
        print(f"  Scaffold {args.name!r} not found.\n")
        return

    # Generate
    overrides = {}
    for kv in args.var:
        if "=" in kv:
            k, v = kv.split("=", 1)
            overrides[k] = v

    try:
        created = generate(args.name, output_dir=args.output, **overrides)
        print(f"\n  Generated {len(created)} files from scaffold {args.name!r}:\n")
        for path in created:
            rel = path.relative_to(Path(args.output).resolve())
            print(f"    {rel}")
        print()
    except ValueError as exc:
        print(f"  Error: {exc}")
        sys.exit(1)


def cmd_init(args: argparse.Namespace) -> None:
    """Interactive project initialization wizard."""
    from virgo_init import run_wizard
    run_wizard(args)


# ===========================================================================
# Argument parser
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="virgo",
        description="multi-agent state machine",
        epilog="see 'virgo <command> --help' for details",
    )
    parser.add_argument("--version", "-V", action="store_true",
                        help="Show version and exit")
    sub = parser.add_subparsers(dest="command", required=False)

    # run
    p_run = sub.add_parser("run", help="Run the pipeline")
    p_run.add_argument("--goal", "-g", default="Scan and parse mock_logs.txt",
                       help="Goal string for the pipeline")
    p_run.add_argument("--iterations", "-i", type=int, default=3,
                       help="Max WTF iterations")
    p_run.add_argument("--name", "-n", default=None,
                       help="Session name for persistence")
    p_run.add_argument("--llm", action="store_true",
                       help="Use LLM-backed policies (requires Ollama)")
    p_run.add_argument("--critic", action="store_true",
                       help="Run static code analysis on generated files")
    p_run.add_argument("--auto-depend", action="store_true",
                       help="Auto-install third-party imports in agent_env")
    p_run.add_argument("--config", "-c", default=None,
                       help="Pipeline config file (.json or .yaml)")
    p_run.add_argument("--yes", "-y", action="store_true",
                       help="Auto-approve plans (non-interactive)")
    p_run.add_argument("--router", "-r", default=None,
                       help="Path to JSON router config "
                            "(overrides ROUTER_* env vars & --crush)")
    p_run.add_argument("--crush", action="store_true",
                       help="Use Crush CLI backend for all roles")
    p_run.add_argument("--stream", action="store_true",
                       help="Stream LLM output token-by-token")
    p_run.add_argument("--no-stream", action="store_true",
                       help="Disable streaming (default: on when interactive)")
    p_run.add_argument("--fast", action="store_true",
                       help="Faster generation: skip chain-of-thought, lower token cap")
    p_run.add_argument("--fallback-model", default=None,
                       help="Fallback model to use when primary LLM fails for all roles")
    p_run.add_argument("--lang", "-l", default="py",
                       choices=["py", "js", "ts", "rs", "go"],
                       help="Target language: py (default), js, ts, rs, go")
    p_run.add_argument("--git", action="store_true",
                       help="Auto-commit changes after a successful pipeline run")
    p_run.add_argument("--git-push", action="store_true",
                       help="Push after auto-commit (implies --git)")
    p_run.add_argument("--git-branch", default=None,
                       help="Create and switch to a branch before running (implies --git)")
    p_run.set_defaults(func=cmd_run)

    # serve
    p_serve = sub.add_parser("serve", help="Start the web dashboard")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", "-p", type=int, default=8765)
    p_serve.set_defaults(func=cmd_serve)

    # list
    p_list = sub.add_parser("list", help="List saved sessions")
    p_list.set_defaults(func=cmd_list)

    # replay
    p_replay = sub.add_parser("replay", help="Replay a saved session")
    p_replay.add_argument("session", help="Session name or path")
    p_replay.add_argument("--iterations", "-i", type=int, default=3)
    p_replay.add_argument("--llm", action="store_true")
    p_replay.add_argument("--fast", action="store_true",
                          help="Faster generation: skip chain-of-thought, lower token cap")
    p_replay.set_defaults(func=cmd_replay)

    # swarm
    p_swarm = sub.add_parser("swarm", help="Multi-agent delegation")
    p_swarm.add_argument("--goal", "-g", required=True,
                         help="Overarching goal for the swarm")
    p_swarm.add_argument("--agent", "-a", action="append",
                         help="Sub-agent definition: name:goal (repeatable)")
    p_swarm.add_argument("--agent-file", "-f", default=None,
                         help="JSON file with list of {name, goal} objects")
    p_swarm.add_argument("--iterations", "-i", type=int, default=3)
    p_swarm.add_argument("--llm", action="store_true",
                         help="Use LLM-backed policies for each agent")
    p_swarm.add_argument("--share", action="store_true",
                         help="Enable shared blackboard between agents")
    p_swarm.add_argument("--ordered", action="store_true",
                         help="Run agents sequentially (each sees prior results)")
    p_swarm.add_argument("--name", "-n", default=None,
                         help="Session name for persistence")
    p_swarm.set_defaults(func=cmd_swarm)

    # watch
    p_watch = sub.add_parser("watch", help="Watch a directory and re-run pipeline on changes")
    p_watch.add_argument("--dir", "-d", default=".",
                         help="Directory to watch (default: .)")
    p_watch.add_argument("--goal", "-g", default="auto-fix broken code",
                         help="Pipeline goal (default: auto-fix broken code)")
    p_watch.add_argument("--interval", "-i", type=float, default=2.0,
                         help="Poll interval in seconds (default: 2.0)")
    p_watch.add_argument("--debounce", type=float, default=1.0,
                         help="Quiet period s after last change")
    p_watch.add_argument("--exclude", "-x", action="append", default=[],
                         help="Additional exclude pattern (repeatable)")
    p_watch.add_argument("--iterations", type=int, default=3,
                         help="Max WTF iterations")
    p_watch.add_argument("--llm", action="store_true",
                         help="Use LLM-backed policies")
    p_watch.add_argument("--crush", action="store_true",
                         help="Use Crush CLI backend")
    p_watch.add_argument("--router", default=None,
                         help="Path to router JSON config")
    p_watch.add_argument("--stream", action="store_true",
                         help="Stream LLM output")
    p_watch.add_argument("--no-stream", action="store_true",
                         help="Disable streaming (default: on when interactive)")
    p_watch.add_argument("--fast", action="store_true",
                         help="Faster generation: skip chain-of-thought, lower token cap")
    p_watch.set_defaults(func=cmd_watch)

    # feedback
    p_fb = sub.add_parser("feedback", help="Show feedback memory")
    p_fb.set_defaults(func=cmd_feedback)

    # demo
    p_demo = sub.add_parser("demo", help="Run the demo pipeline (deterministic policies)")
    p_demo.add_argument("--goal", "-g", default=None,
                        help="Optional goal override for the demo pipeline")
    p_demo.set_defaults(func=cmd_demo)

    # diff
    # self-install
    p_self = sub.add_parser("self-install", help="Add virgo to system PATH")
    p_self.set_defaults(func=cmd_self_install)

    # config
    p_cfg = sub.add_parser("config", help="View or set virgo configuration")
    p_cfg.add_argument("--get", default=None, help="Get a config value by key")
    p_cfg.add_argument("--set", default=None, help="Set a config value (KEY=VALUE)")
    p_cfg.add_argument("--unset", default=None, help="Remove a config key")
    p_cfg.set_defaults(func=cmd_config)

    # diff
    p_diff = sub.add_parser("diff", help="Compare two saved sessions")
    p_diff.add_argument("session_a", help="First session name or .json path")
    p_diff.add_argument("session_b", help="Second session name or .json path")
    p_diff.add_argument("--brief", "-b", action="store_true",
                        help="Only list file names, no content diffs")
    p_diff.add_argument("--output", "-o", default=None,
                        help="Write diff report to file (.md or .txt)")
    p_diff.set_defaults(func=cmd_diff)

    # templates
    p_tpl = sub.add_parser("templates", help="List and generate from templates")
    p_tpl.add_argument("--generate", "-g", default=None,
                       help="Template key to generate from")
    p_tpl.add_argument("--output", "-o", default=None,
                       help="Output file path")
    p_tpl.add_argument("--name", "-n", default=None,
                       help="Project/script name")
    p_tpl.add_argument("--description", "-d", default=None,
                       help="Description for the generated file")
    p_tpl.add_argument("--target", "-t", default=None,
                       help="Target module for test templates")
    p_tpl.set_defaults(func=cmd_templates)

    # export
    p_exp = sub.add_parser("export", help="Export a session as HTML or Markdown")
    p_exp.add_argument("session", help="Session name or path")
    p_exp.add_argument("--format", "-f", choices=["html", "md"], default="html",
                       help="Output format")
    p_exp.add_argument("--output", "-o", default=None,
                       help="Output file path")
    p_exp.set_defaults(func=cmd_export)

    # plugins
    p_plug = sub.add_parser("plugins", help="List and load plugins")
    p_plug.add_argument("--load", "-l", action="store_true",
                        help="Load all plugins and show registered tools")
    p_plug.set_defaults(func=cmd_plugins)

    # scaffold
    p_scaffold = sub.add_parser("scaffold", help="Generate project from a scaffold")
    p_scaffold.add_argument("name", nargs="?", default=None,
                            help="Scaffold name (omit to list)")
    p_scaffold.add_argument("--output", "-o", default=".",
                            help="Output directory")
    p_scaffold.add_argument("--var", "-v", action="append", default=[],
                            help="Template variable (key=value)")
    p_scaffold.add_argument("--install", action="store_true",
                            help="Install a scaffold package from PyPI")
    p_scaffold.add_argument("--uninstall", action="store_true",
                            help="Uninstall a scaffold package")
    p_scaffold.set_defaults(func=cmd_scaffold, command=None)

    # init
    p_init = sub.add_parser("init", help="Interactive project initialization wizard")
    p_init.add_argument("name", nargs="?", default=None,
                        help="Scaffold name (omit to pick from list)")
    p_init.add_argument("--output", "-o", default=".",
                        help="Output directory (default: current dir)")
    p_init.add_argument("--non-interactive", action="store_true",
                        help="Skip prompts, use default variable values")
    p_init.set_defaults(func=cmd_init)

    # version
    p_ver = sub.add_parser("version", help="Show version information")
    p_ver.set_defaults(func=cmd_version)

    # update
    p_upd = sub.add_parser("update", help="Pull latest version from git")
    p_upd.set_defaults(func=cmd_update)

    # doctor
    p_doc2 = sub.add_parser("doctor", help="Run environment health checks")
    p_doc2.set_defaults(func=cmd_doctor)

    # completion
    p_comp = sub.add_parser("completion", help="Generate shell completion script")
    p_comp.add_argument("shell", choices=["bash", "zsh", "powershell"],
                        help="Shell to generate completion for")
    p_comp.set_defaults(func=cmd_completion)

    # testgen
    p_tg = sub.add_parser("testgen", help="Generate pytest test stubs from Python source files")
    p_tg.add_argument("--path", "-p", default=None,
                      help="Single Python file to analyze")
    p_tg.add_argument("--dir", "-d", default=None,
                      help="Directory to scan recursively for .py files")
    p_tg.add_argument("--output", "-o", default="./tests",
                      help="Output directory for generated test files (default: ./tests)")
    p_tg.add_argument("--overwrite", action="store_true",
                      help="Overwrite existing test files without warning")
    p_tg.set_defaults(func=cmd_testgen)

    # commit
    p_commit = sub.add_parser("commit", help="Stage all changes and commit")
    p_commit.add_argument("-m", "--message", default="",
                          help="Commit message (auto-generated if omitted)")
    p_commit.add_argument("--push", action="store_true",
                          help="Push after commit")
    p_commit.add_argument("--amend", action="store_true",
                          help="Amend the last commit")
    p_commit.set_defaults(func=cmd_commit)

    # doc
    p_doc = sub.add_parser("doc", help="Generate API documentation from docstrings")
    p_doc.add_argument("--path", "-p", default=".",
                       help="Path to scan (file or directory). Default: current dir.")
    p_doc.add_argument("--output", "-o", default="docs",
                       help="Output directory. Default: docs/")
    p_doc.add_argument("--format", "-f", choices=["md", "html"], default="md",
                       help="Output format: md (markdown, default) or html.")
    p_doc.add_argument("--recursive", "-r", action="store_true",
                       help="Walk directories recursively.")
    p_doc.add_argument("--name", "-n", default="virgo",
                       help="Project display name. Default: 'virgo'")
    p_doc.set_defaults(func=cmd_doc)

    # agent — autonomous runtime (ReAct loop over tools)
    p_agent = sub.add_parser("agent", help="Run the autonomous agent runtime")
    p_agent.add_argument("--goal", "-g", required=True,
                         help="Goal for the autonomous agent to accomplish")
    p_agent.add_argument("--steps", "-i", type=int, default=12,
                         help="Max ReAct steps per attempt (default: 12)")
    p_agent.add_argument("--retries", "-r", type=int, default=2,
                         help="Max evaluation-retry attempts (default: 2)")
    p_agent.add_argument("--llm", action="store_true",
                         help="Use LLM-backed policies (requires Ollama)")
    p_agent.add_argument("--no-mcp", action="store_true",
                         help="Disable MCP server discovery/bridge")
    p_agent.add_argument("--mcp", action="append", default=[],
                         help="Explicit MCP server spec name=cmd args (repeatable)")
    p_agent.add_argument("--no-experience", action="store_true",
                         help="Disable experience memory")
    p_agent.add_argument("--stream", action="store_true",
                         help="Stream LLM output")
    p_agent.add_argument("--no-stream", action="store_true",
                         help="Disable streaming (default: on when interactive)")
    p_agent.set_defaults(func=cmd_agent)

    # chat
    p_chat = sub.add_parser("chat", help="Interactive chat with virgo")
    p_chat.add_argument("--resume", default=None,
                        help="Resume a previous chat session (name or path)")
    p_chat.set_defaults(func=cmd_chat)

    # chat-ls
    p_cls = sub.add_parser("chat-ls", help="List saved chat sessions")
    p_cls.set_defaults(func=lambda _: _list_chats(HERE / ".virgo_memory" / "chats"))

    args = parser.parse_args()
    if args.version:
        cmd_version(args)
    elif args.command is None:
        cmd_menu(args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
