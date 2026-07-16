"""agent_runtime — Virgo's autonomous "Act" loop.

This is the leap from a *code-generating pipeline* to an *autonomous agent*:
instead of only writing files, Virgo can now **reason, act through tools,
observe results, and reflect** until a goal is met — a ReAct loop.

Pipeline (per goal)::

    PLAN   -> LLM breaks the goal into a short plan + chooses first action
    ACT    -> parse tool calls from the LLM output, execute them via the
             ToolRegistry (builtin tools + any MCP servers)
    OBSERVE-> append tool results to the transcript
    REFLECT-> LLM reviews transcript, decides next action or 'DONE'
    EVALUATE-> quality gate decides pass/fail; on fail, loop again (budgeted)

The runtime is provider-agnostic: pass any OpenAI-compatible client with a
``.chat(messages, role=...)`` method (e.g. ``main.LLMClient``). With no
client it still runs a deterministic heuristic loop so the machinery is
always testable.

Experience memory (``experience.py``) injects past lessons into the prompt
and records every run's outcome, so Virgo stops re-solving the same problem.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── Progress callback type ──────────────────────────────────────────
ProgressCallback = Callable[[str, str, Optional[str]], None]
# Arguments: (phase: str, message: str, detail: str | None)
# phase is one of: "step", "tool", "eval", "retry", "done", "error"

from _log import log

try:
    from tools_core import ToolRegistry, make_builtin_registry, parse_tool_calls
except Exception as exc:  # pragma: no cover
    log.warning("agent_runtime: tools_core unavailable (%s)", exc)
    ToolRegistry = None  # type: ignore
    make_builtin_registry = None  # type: ignore
    parse_tool_calls = None  # type: ignore

try:
    from experience import ExperienceMemory, get_memory
except Exception as exc:  # pragma: no cover
    log.warning("agent_runtime: experience unavailable (%s)", exc)
    ExperienceMemory = None  # type: ignore

    def get_memory() -> None:  # type: ignore
        return None

try:
    from evaluator import evaluate, Evaluation
except Exception as exc:  # type: ignore
    log.warning("agent_runtime: evaluator unavailable (%s)", exc)
    Evaluation = None  # type: ignore

    def evaluate(*a, **k):  # type: ignore
        return None


# ── Config / result types ─────────────────────────────────────────────

@dataclass
class AgentConfig:
    """Tunables for a single agent run."""

    max_steps: int = 12
    max_retries: int = 2
    model: str = "qwen2.5-coder:7b"
    use_experience: bool = True
    mcp_specs: Optional[list[str]] = None
    stream: bool = False


@dataclass
class AgentResult:
    goal: str
    passed: bool
    steps: int
    transcript: str
    tools_used: list[str] = field(default_factory=list)
    evaluation: Optional[Any] = None
    lessons: list[str] = field(default_factory=list)


# ── System prompt ─────────────────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent(
    """\
    You are Virgo, an autonomous agent that ACCOMPLISHES goals by using tools.
    Cycle: think, then call ONE tool, observe the result, and repeat until
    the goal is complete. When done, output a single line: DONE

    To use a tool, emit EXACTLY this format:

    Tool: <tool_name>
    ARGS: <arguments for the tool>

    Rules:
    - Call one tool at a time. Wait for the result before the next step.
    - Use the `think` tool to reason out loud when planning.
    - Prefer `file_write`/`python_run`/`shell` to actually produce results.
    - Never invent tool names. Only use tools listed below.
    - When the goal is fully achieved, output `DONE` on its own line.

    AVAILABLE TOOLS:
    {tool_list}

    {experience}
    """
)


# ── The runtime ───────────────────────────────────────────────────────

class AgentRuntime:
    """ReAct loop over a tool registry, backed by an LLM client."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        client: Any = None,
        memory: Any = None,
        config: Optional[AgentConfig] = None,
    ) -> None:
        self.registry = registry or (make_builtin_registry() if make_builtin_registry else ToolRegistry())
        self.client = client
        self.memory = memory or (get_memory() if get_memory else None)
        self.config = config or AgentConfig()
        self.transcript: list[str] = []
        self.tools_used: list[str] = []

    # -- public API ------------------------------------------------------
    def run(self, goal: str, *, progress_callback: Optional[ProgressCallback] = None) -> AgentResult:
        """Execute a goal and return an AgentResult.

        If *progress_callback* is provided, it is called on each significant
        event::

            progress_callback("step", "Planning…", detail=None)
            progress_callback("tool", "file_write", detail="wrote main.py")
            progress_callback("eval", "Evaluating…", detail=None)
            progress_callback("retry", "Retry 2/3", detail="Reason for retry")
            progress_callback("done", "Goal met", detail=None)
            progress_callback("error", str(exc), detail=None)
        """
        _progress = progress_callback or (lambda phase, msg, detail=None: None)

        log.info("agent: starting goal=%r", goal)
        self.transcript = []
        self.tools_used = []

        _progress("step", f"Starting goal: {goal[:80]}")
        experience_block = ""
        if self.config.use_experience and self.memory is not None:
            try:
                experience_block = self.memory.format_for_prompt(goal, k=3)
            except Exception as exc:  # pragma: no cover
                log.warning("agent: experience lookup failed: %s", exc)

        system = SYSTEM_PROMPT.format(
            tool_list=self._tool_list(),
            experience=experience_block,
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"GOAL: {goal}"},
        ]

        attempts = 0
        last_eval = None
        while attempts <= self.config.max_retries:
            attempts += 1
            if attempts > 1:
                _progress("retry", f"Retry {attempts}/{self.config.max_retries + 1}",
                          detail="Previous attempt did not satisfy the goal")
            self._loop(messages, goal, progress_callback=_progress)
            # Evaluate
            transcript_text = "\n".join(self.transcript)
            _progress("eval", "Evaluating result…")
            if Evaluation is not None:
                try:
                    last_eval = evaluate(
                        goal, transcript_text,
                        client=self._evaluator_client(),
                    )
                except Exception as exc:  # pragma: no cover
                    log.warning("agent: eval failed: %s", exc)
                    last_eval = None
            passed = (last_eval.passed if last_eval else self._heuristic_pass(transcript_text))
            if passed:
                break
            # Reflect + retry with feedback
            messages.append(
                {"role": "assistant", "content": transcript_text[-4000:]}
            )
            messages.append(
                {"role": "user", "content": (
                    "That attempt did not fully satisfy the goal. "
                    "Review what went wrong and try a different approach. "
                    "Output DONE only when the goal is truly met."
                )}
            )
            log.info("agent: retry %d/%d", attempts, self.config.max_retries)

        _progress("done", "Goal completed" if passed else f"Goal failed after {attempts} attempt(s)")
        transcript_text = "\n".join(self.transcript)
        passed = (last_eval.passed if last_eval else self._heuristic_pass(transcript_text))

        lessons = self._extract_lessons(transcript_text)
        if self.config.use_experience and self.memory is not None:
            try:
                self.memory.add(
                    goal=goal,
                    approach="react-loop",
                    tools_used=sorted(set(self.tools_used)),
                    outcome="success" if passed else "failure",
                    success=passed,
                    lesson=lessons[0] if lessons else "",
                )
            except Exception as exc:  # pragma: no cover
                log.warning("agent: memory write failed: %s", exc)
                _progress("error", f"Memory write failed: {exc}")

        return AgentResult(
            goal=goal,
            passed=passed,
            steps=len([t for t in self.transcript if t.startswith("ACTION")]),
            transcript=transcript_text,
            tools_used=sorted(set(self.tools_used)),
            evaluation=last_eval,
            lessons=lessons,
        )

    # -- internal loop ---------------------------------------------------
    def _loop(self, messages: list[dict], goal: str,
              progress_callback: ProgressCallback = lambda p, m, d=None: None) -> int:
        steps = 0
        for step in range(self.config.max_steps):
            steps += 1
            progress_callback("step", f"Step {step + 1}/{self.config.max_steps}",
                            detail=f"Thinking about: {goal[:60]}")
            reply = self._ask(messages)
            self.transcript.append(f"AGENT:\n{reply}")
            messages.append({"role": "assistant", "content": reply})

            calls = parse_tool_calls(reply) if parse_tool_calls else []
            if not calls:
                if re.search(r"(?m)^DONE\b", reply):
                    self.transcript.append("OBSERVE: agent signaled DONE (no tools)")
                    progress_callback("done", "Agent signaled DONE")
                    break
                # Nudge the model to actually act.
                self.transcript.append("OBSERVE: no tool call parsed; prompting for action")
                messages.append(
                    {"role": "user", "content": "You must call a tool now (see AVAILABLE TOOLS)."}
                )
                continue

            # ReAct discipline: execute ONLY the first tool call, then feed
            # back the REAL observation. Models often batch several calls and
            # hallucinate their results (and a premature DONE) in one reply;
            # ignoring the extras forces grounding in actual tool output.
            name, args = calls[0]
            progress_callback("tool", name, detail=args[:120])
            result = self._dispatch(name, args)
            self.tools_used.append(name)
            self.transcript.append(f"OBSERVE [{name}]:\n{result}")
            note = ""
            if len(calls) > 1:
                note = ("\n(Note: only your FIRST tool call was executed. "
                        "Do not assume results for others — wait for each observation.)")
            messages.append(
                {"role": "user", "content": f"RESULT of {name}:\n{result[:6000]}{note}"}
            )
            # A same-turn DONE is based on hallucinated observations — ignore
            # it and let the model react to the real result on the next turn.
        return steps

    def _dispatch(self, name: str, args: str) -> str:
        self.transcript.append(f"ACTION: {name}")
        tool = self.registry.get(name)
        if tool is None:
            return f"ERROR: unknown tool '{name}'. Available: " + ", ".join(
                t.name for t in self.registry.list_tools()
            )
        try:
            return tool.run(args)
        except Exception as exc:  # pragma: no cover
            return f"ERROR: tool '{name}' raised {exc}"

    def _ask(self, messages: list[dict]) -> str:
        if self.client is None:
            # Deterministic fallback: pick the first plausible builtin tool.
            return self._deterministic_reply(messages)
        try:
            if self.config.stream and hasattr(self.client, "chat_stream"):
                return self.client.chat_stream(messages, role="agent")
            if hasattr(self.client, "chat"):
                return self.client.chat(messages, role="agent")
            return str(self.client(messages))
        except Exception as exc:  # pragma: no cover
            log.warning("agent: LLM call failed: %s", exc)
            return f"ERROR: llm call failed: {exc}\nDONE"

    def _deterministic_reply(self, messages: list[dict]) -> str:
        """No-LLM fallback that respects one-tool-per-turn ReAct discipline.

        Progresses by inspecting the transcript: think -> file_write -> DONE.
        Keeps the loop fully exercisable in tests without an LLM.
        """
        joined = "\n".join(self.transcript)
        goal = ""
        for m in messages:
            if m["role"] == "user" and m["content"].startswith("GOAL:"):
                goal = m["content"]
                break
        if "OBSERVE [file_write]" in joined:
            return "The result file was written successfully.\nDONE"
        if "OBSERVE [think]" in joined:
            return (
                "Tool: file_write\n"
                f"ARGS: _agent_result.txt\n---\nGOAL MET: {goal}\n"
            )
        return f"Tool: think\nARGS: planning how to accomplish: {goal}"

    # -- helpers ---------------------------------------------------------
    def _tool_list(self) -> str:
        lines = []
        for t in self.registry.list_tools():
            schema = getattr(t, "schema", "") or ""
            if schema:
                lines.append(f"  - {t.name} -- {t.description}\n      ARGS format: {schema}")
            else:
                lines.append(f"  - {t.name} -- {t.description}")
        return "\n".join(lines) if lines else "  (no tools registered)"

    def _evaluator_client(self):
        # Reuse the same client but tag the evaluator role.
        return self.client

    def _heuristic_pass(self, transcript: str) -> bool:
        if len(transcript) < 50:
            return False
        if "ERROR:" in transcript:
            # Any tool error => not clean; still allow if DONE present.
            return "DONE" in transcript
        return "DONE" in transcript

    def _extract_lessons(self, transcript: str) -> list[str]:
        lessons: list[str] = []
        for m in re.finditer(r"LESSON:\s*(.+)", transcript):
            lessons.append(m.group(1).strip())
        return lessons


# ── Convenience factory ───────────────────────────────────────────────

def build_runtime(
    client: Any = None,
    config: Optional[AgentConfig] = None,
    include_mcp: bool = True,
) -> AgentRuntime:
    """Assemble a runtime with builtin tools (+ MCP if available)."""
    registry = make_builtin_registry() if make_builtin_registry else ToolRegistry()
    if include_mcp:
        try:
            from mcp_bridge import build_mcp_registry
            mcp = build_mcp_registry(
                explicit=(config.mcp_specs if config else None)
            )
            for t in mcp.list_tools():
                registry.register(t)
        except Exception as exc:  # pragma: no cover
            log.info("agent: MCP disabled (%s)", exc)
    memory = None
    if get_memory:
        try:
            memory = get_memory()
        except Exception:  # pragma: no cover
            memory = None
    return AgentRuntime(registry=registry, client=client, memory=memory, config=config)
