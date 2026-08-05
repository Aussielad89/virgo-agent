"""Tests for the build-on-top feature modules (session, approval, artifacts,
memory, runbooks, router, rag, budget, autoheal, docker sandbox, runtime)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── session_store ──────────────────────────────────────────────────────


def test_session_checkpoint_roundtrip(tmp_path: Path) -> None:
    from session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    snap = store.new_session("write a report", session_id="my-run")
    assert snap.session_id == "my-run"

    snap.steps_used = 5
    snap.transcript = ["AGENT: think", "ACTION: file_write"]
    store.save_checkpoint(snap)

    loaded = store.load_checkpoint("my-run")
    assert loaded is not None
    assert loaded.goal == "write a report"
    assert loaded.steps_used == 5
    assert loaded.transcript == ["AGENT: think", "ACTION: file_write"]

    store.mark_done("my-run", status="done", transcript_text="hello")
    assert store.load_checkpoint("my-run").status == "done"
    assert (tmp_path / "sessions" / "my-run" / "transcript.txt").exists()


def test_session_events_and_list(tmp_path: Path) -> None:
    from session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    store.new_session("goal one", session_id="a")
    store.new_session("goal two", session_id="b")
    store.append_event("a", "step", "Step 1")
    store.append_event("a", "tool", "file_write", detail="wrote x")
    events = store.read_events("a")
    assert [e["phase"] for e in events] == ["step", "tool"]
    assert events[-1]["detail"] == "wrote x"

    rows = store.list_sessions()
    ids = {r["session_id"] for r in rows}
    assert ids == {"a", "b"}

    assert store.delete("a") is True
    assert store.delete("missing") is False
    assert store.load_checkpoint("a") is None


# ── approval ───────────────────────────────────────────────────────────


def test_approval_gate_hook_deny() -> None:
    from approval import ApprovalGate

    gate = ApprovalGate(hook=lambda tool, args, risk: False)
    assert gate.approve("shell", "rm -rf /", 4) is False


def test_approval_gate_hook_allow() -> None:
    from approval import ApprovalGate

    gate = ApprovalGate(hook=lambda tool, args, risk: risk < 3)
    assert gate.approve("file_read", "foo.py", 1) is True
    assert gate.approve("shell", "rm -rf /", 4) is False


def test_approval_gate_no_hook_allows() -> None:
    from approval import ApprovalGate

    assert ApprovalGate().approve("shell", "echo hi", 4) is True


def test_interactive_approval_remembers() -> None:
    from approval import InteractiveApproval

    ia = InteractiveApproval()
    ia._decisions["shell"] = False
    assert ia("shell", "rm -rf", 4) is False
    ia._decisions["file_read"] = True
    assert ia("file_read", "x", 1) is True


def test_registry_approval_gate_blocks_call(tmp_path: Path) -> None:
    from approval import ApprovalGate
    from tools_core import Tool, ToolRegistry

    reg = ToolRegistry()
    reg.register(Tool(name="shell", description="run", run=lambda args: "ran"))
    reg.approval_gate = ApprovalGate(hook=lambda t, a, r: False)
    reg.approval_threshold = 2  # anything >= RISK_LOW triggers the gate
    assert "denied" in reg.call("shell", "echo hi")

    reg.approval_gate = ApprovalGate(hook=lambda t, a, r: True)
    assert reg.call("shell", "echo hi") == "ran"


# ── artifact_store ─────────────────────────────────────────────────────


def test_artifact_versioning_and_diff(tmp_path: Path) -> None:
    from artifact_store import ArtifactStore

    store = ArtifactStore(tmp_path / "artifacts")
    v1 = store.store("report", "hello world", meta={"goal": "x"})
    v2 = store.store("report", "hello brave world")
    assert v2 == v1 + 1

    assert store.versions("report")[-1]["version"] == 2
    latest = store.get("report")
    assert latest["data"] == "hello brave world"
    assert latest["version"] == 2

    diff = store.diff("report")
    assert "hello world" in diff and "hello brave world" in diff

    with pytest.raises(KeyError):
        store.get("nope")
    with pytest.raises(KeyError):
        store.get("report", 99)

    rows = store.list()
    assert rows[0]["name"] == "report" and rows[0]["versions"] == 2
    assert store.delete("report") is True


# ── memory_store ───────────────────────────────────────────────────────


def test_unified_memory_remember_recall_profile(tmp_path: Path) -> None:
    from memory_store import UnifiedMemory

    mem = UnifiedMemory(tmp_path / "mem")
    mem.remember(
        "build a web scraper for prices",
        "react-loop",
        ["file_write"],
        "success",
        True,
        lesson="use requests and parse with regex",
    )
    mem.profile.set("name", "Ada")

    assert mem.profile.get("name") == "Ada"
    assert mem.profile.get("missing", "dflt") == "dflt"

    hits = mem.recall("scrape prices from the web", k=5)
    assert hits, "recall should find the remembered goal"
    assert "web scraper" in hits[0]["goal"]

    block = mem.format_for_prompt("web scraper prices")
    assert "USER PROFILE:" in block
    assert "Ada" in block

    stats = mem.stats()
    assert stats["profile_facts"] >= 1


# ── runbook ────────────────────────────────────────────────────────────


def test_runbook_generate_from_repeated_failures(tmp_path: Path) -> None:
    from memory_store import UnifiedMemory
    from runbook import RunbookGenerator

    mem = UnifiedMemory(tmp_path / "mem")
    for i in range(3):
        mem.remember(
            f"deploy the dashboard service {i}",
            "react-loop",
            ["shell"],
            "failed",
            False,
            lesson="check the port binding before deploying",
        )
    mem.remember("unrelated task", "react-loop", [], "failed", False, lesson="nothing")

    gen = RunbookGenerator(kb_dir=tmp_path / "kb", memory=mem)
    written = gen.generate(min_failures=2)
    assert written, "a runbook should be written for the repeated failure cluster"
    text = written[0].read_text(encoding="utf-8")
    assert "Runbook" in text
    assert "port binding" in text


# ── model_router ───────────────────────────────────────────────────────


def test_model_router_evidence_based_route(tmp_path: Path) -> None:
    from model_router import ModelRouter

    router = ModelRouter(tmp_path / "bench.jsonl")
    router.record("small:7b", "generator", True, score=0.9)
    router.record("small:7b", "generator", True, score=0.8)
    router.record("big:70b", "generator", False, score=0.2)
    router.record("medium:14b", "generator", True, score=0.85)

    picked = router.route("generator")
    assert picked == "small:7b"  # best pass rate + cheap, never-failed only

    assert "PASS" in router.report("generator")


def test_model_router_falls_back_to_defaults() -> None:
    from model_router import ModelRouter

    router = ModelRouter(Path("nope") / "bench.jsonl")
    picked = router.route("chat")
    assert isinstance(picked, str) and picked


# ── local_rag ──────────────────────────────────────────────────────────


def test_local_rag_virtual_docs(tmp_path: Path) -> None:
    from local_rag import LocalRag

    rag = LocalRag(virtual_path=tmp_path / "virtual.json", kb_engine=None)
    rag.add_virtual("run-note", "run this project with python main.py --demo")
    hits = rag.query("how do i run the demo", k=3)
    assert any(h["source"] == "note:run-note" for h in hits)

    block = rag.inject("how do i run the demo")
    assert "KNOWLEDGE BASE" in block and "main.py" in block

    assert rag.remove_virtual("run-note") is True
    assert rag.query("how do i run the demo") == []


# ── budget ─────────────────────────────────────────────────────────────


def test_budget_spend_and_limit(tmp_path: Path) -> None:
    from budget import BudgetTracker

    tracker = BudgetTracker(tmp_path / "budget.jsonl", limit=0.5)
    tracker.spend("gpt-4o", "a" * 400000, goal="big run")
    v = tracker.check()
    assert v["over"] is True
    assert v["cost"] > 0
    assert v["remaining"] == 0

    tracker.set_limit(0.0)
    assert tracker.check()["over"] is False

    rows = tracker.recent(5)
    assert rows and rows[0]["model"] == "gpt-4o"


def test_budget_local_model_free() -> None:
    from budget import BudgetTracker

    tracker = BudgetTracker(Path("nope") / "budget.jsonl")
    tracker.spend("ornith:latest", "x" * 1000)
    assert tracker.check()["cost"] == 0.0


# ── autoheal ───────────────────────────────────────────────────────────


def test_autoheal_no_pid_returns_stopped(tmp_path: Path) -> None:
    from autoheal import AutoHeal

    heal = AutoHeal("demo", ["python", "-c", "pass"], state_dir=tmp_path / "heal")
    assert heal.tick() == "stopped"
    assert heal.status()["alive"] is False


def test_autoheal_restart_budget(tmp_path: Path) -> None:
    import time

    from autoheal import AutoHeal

    heal = AutoHeal(
        "demo", ["python", "-c", "pass"],
        state_dir=tmp_path / "heal", max_restarts=2, window_seconds=60,
    )
    now = time.time()
    heal.restart_times = [now - 1.0, now - 2.0]
    assert heal._within_budget() is False


# ── docker_sandbox ─────────────────────────────────────────────────────


def test_docker_sandbox_unavailable_raises() -> None:
    from docker_sandbox import DockerSandbox, DockerUnavailable, docker_available

    # Whether or not docker exists, run() must not run on the host.
    if docker_available():
        pytest.skip("docker present; skipping fail-closed check")
    with pytest.raises(DockerUnavailable):
        DockerSandbox().run(["echo", "hi"])


def test_run_sandboxed_docker_blocked_without_docker() -> None:
    from docker_sandbox import docker_available, run_sandboxed_docker

    if docker_available():
        pytest.skip("docker present; skipping fail-closed check")
    with pytest.raises(ValueError):
        run_sandboxed_docker(["echo", "hi"])


# ── agent_runtime integration (checkpoint/resume + approval) ───────────


def test_runtime_checkpoint_resume(tmp_path: Path) -> None:
    from agent_runtime import AgentConfig, build_runtime
    from session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    cfg = AgentConfig(max_steps=4, max_retries=0, save_session=True, checkpoint_every=1)
    runtime = build_runtime(config=cfg, store=store, include_mcp=False)
    res = runtime.run("write a report file")
    assert res.passed
    assert res.session_id is not None
    assert store.load_checkpoint(res.session_id) is not None

    cfg2 = AgentConfig(max_steps=4, max_retries=0, save_session=True, resume_from=res.session_id)
    runtime2 = build_runtime(config=cfg2, store=store, include_mcp=False)
    res2 = runtime2.run("anything")
    assert res2.session_id == res.session_id


def test_runtime_approval_denies_risky_tool(tmp_path: Path) -> None:
    from agent_runtime import AgentConfig
    from approval import ApprovalGate
    from session_store import SessionStore
    from tools_core import make_builtin_registry

    registry = make_builtin_registry()
    registry.approval_gate = ApprovalGate(hook=lambda t, a, r: False)
    registry.approval_threshold = 1  # gate everything

    from agent_runtime import AgentRuntime

    runtime = AgentRuntime(registry=registry, config=AgentConfig(max_steps=2, max_retries=0),
                           store=SessionStore(tmp_path / "sessions"))
    # The deterministic loop calls think -> file_write; both should be denied
    # and the loop must still terminate with a FAIL verdict.
    res = runtime.run("write a file")
    assert "requires approval" in res.transcript
    assert res.passed is False
