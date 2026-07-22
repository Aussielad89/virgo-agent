"""
virgo — LLM-powered entry point for the multi-agent state machine.

Wires three model-backed policies into the Orchestrator:

  • my_planner    – analyses discovered files and produces a build plan
  • my_generator  – writes code (Qwen2.5 Coder)
  • my_fixer      – analyses test failures and produces patches
                    (Qwen2.5 Coder, swap model for a dedicated reasoner)

Communicates with a local OpenAI-compatible API (Ollama / vLLM /
LM Studio) via ``urllib`` — no ``openai`` package required.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from _console import icon
from environment import AgentEnvironment
from logo import print_logo
from orchestrator import (
    Orchestrator,
    TestLog,
    WorkspaceState,
)
from tools import ToolRegistry

# =========================================================================
# Config — edit these to match your local API setup
# =========================================================================

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-no-key-required")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "300"))

# You can point these at different models if they are available:
MODEL_PLANNER = os.getenv("MODEL_PLANNER", "ornith:latest")
MODEL_GENERATOR = os.getenv("MODEL_GENERATOR", "ornith:latest")
MODEL_FIXER = os.getenv("MODEL_FIXER", "ornith:latest")

# virgo.toml is the source of truth — override model defaults if present.
try:
    from config import load as _cfg_load

    _cfg = _cfg_load()
    _model_cfg = _cfg.get("model", {})
    if _model_cfg.get("planner"):
        MODEL_PLANNER = _model_cfg["planner"]
    if _model_cfg.get("generator"):
        MODEL_GENERATOR = _model_cfg["generator"]
    if _model_cfg.get("fixer"):
        MODEL_FIXER = _model_cfg["fixer"]
except Exception:
    pass

# Fallback models — used when primary LLM call fails
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "")
FALLBACK_MODEL_PLANNER = os.getenv("FALLBACK_PLANNER", "")
FALLBACK_MODEL_GENERATOR = os.getenv("FALLBACK_GENERATOR", "")
FALLBACK_MODEL_FIXER = os.getenv("FALLBACK_FIXER", "")

# Flags — toggled by CLI
USE_CRUSH = False
STREAM_OUTPUT = False
FAST_MODE = False  # --fast: skip CoT block + lower max_tokens
CRUSH_BIN = os.path.expanduser("~/bin/crush.exe")

# --fast per-role output caps (tokens). Lower = faster generation on CPU.
FAST_MAX_TOKENS = {
    "planner": 1024,
    "generator": 4096,  # code needs room; only the CoT block is dropped
    "fixer": 2048,
}

# Router — per-role provider:model map  {role: (provider, model)}
ROUTER_CONFIG: dict[str, tuple[str, str]] | None = None
_ROUTER_ENV_LOADED = False


def router_from_env() -> dict[str, tuple[str, str]] | None:
    """Read ROUTER_PLANNER / ROUTER_GENERATOR / ROUTER_FIXER env vars.

    Format:  ROUTER_PLANNER=ollama:qwen2.5-coder:32b
             ROUTER_GENERATOR=crush:opencode-zen/deepseek-v4-flash-free
    Returns None when no env vars are set.
    """
    config: dict[str, tuple[str, str]] = {}
    for role in ("planner", "generator", "fixer"):
        val = os.environ.get(f"ROUTER_{role.upper()}")
        if val and ":" in val:
            provider, model = val.split(":", 1)
            config[role] = (provider.strip(), model.strip())
    return config if config else None


def router_from_file(path: str) -> dict[str, tuple[str, str]]:
    """Load a router JSON config file.

    Expected format::
        {
            "planner":  {"provider": "ollama", "model": "qwen2.5-coder:32b"},
            "generator": {"provider": "crush",  "model": "opencode-zen/..."},
            "fixer":    {"provider": "ollama", "model": "qwen2.5-coder:7b"}
        }
    """
    import json

    with open(path) as f:
        data = json.load(f)
    config: dict[str, tuple[str, str]] = {}
    for role in ("planner", "generator", "fixer"):
        if role in data:
            config[role] = (data[role]["provider"], data[role]["model"])
    return config


def _ensure_router_loaded() -> None:
    """Lazy-load router from env on first access (only if not already set)."""
    global ROUTER_CONFIG, _ROUTER_ENV_LOADED
    if not _ROUTER_ENV_LOADED and ROUTER_CONFIG is None:
        cfg = router_from_env()
        if cfg:
            ROUTER_CONFIG = cfg
        _ROUTER_ENV_LOADED = True


def _model_for_role(role: str) -> str:
    """Return the model name configured for *role* (respects router)."""
    _ensure_router_loaded()
    if ROUTER_CONFIG and role in ROUTER_CONFIG:
        return ROUTER_CONFIG[role][1]
    return {
        "planner": MODEL_PLANNER,
        "generator": MODEL_GENERATOR,
        "fixer": MODEL_FIXER,
    }.get(role, MODEL_PLANNER)


def _fallback_model_for_role(role: str) -> str:
    """Return the configured fallback model for *role*."""
    if FALLBACK_MODEL:
        return FALLBACK_MODEL
    return {
        "planner": FALLBACK_MODEL_PLANNER,
        "generator": FALLBACK_MODEL_GENERATOR,
        "fixer": FALLBACK_MODEL_FIXER,
    }.get(role, "")


_PROVIDER_BASE_URLS: dict[str, str] = {
    "ollama": os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def get_client(model: str = "") -> LLMClient | CrushClient:
    """Legacy — return a single client (backward compat)."""
    if USE_CRUSH:
        return CrushClient(model=model)
    return LLMClient(model=model or MODEL_PLANNER)


def get_client_for(role: str = "generator") -> LLMClient | CrushClient:
    """Return a client for *role*, checking the router config first."""
    _ensure_router_loaded()
    if ROUTER_CONFIG and role in ROUTER_CONFIG:
        provider, model = ROUTER_CONFIG[role]
        if provider == "crush":
            return CrushClient(model=model)
        base_url = _PROVIDER_BASE_URLS.get(
            provider,
            os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        )
        return LLMClient(model=model, base_url=base_url)
    # Fallback: old behaviour
    return get_client()


def _make_fallback_client(role: str, fallback_model: str) -> LLMClient | CrushClient:
    """Create a client using the fallback model for *role*."""
    _ensure_router_loaded()
    if ROUTER_CONFIG and role in ROUTER_CONFIG:
        provider, _ = ROUTER_CONFIG[role]
        if provider == "crush":
            return CrushClient(model=fallback_model)
        base_url = _PROVIDER_BASE_URLS.get(
            provider,
            os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        )
        return LLMClient(model=fallback_model, base_url=base_url)
    return LLMClient(model=fallback_model)


# =========================================================================
# Lightweight OpenAI-compatible client (stdlib only)
# =========================================================================


class LLMClient:
    """Minimal OpenAI chat-completion client using ``urllib``."""

    def __init__(
        self,
        base_url: str = LLM_BASE_URL,
        model: str = "qwen2.5-coder:7b",
        api_key: str = LLM_API_KEY,
        timeout: int = LLM_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        role: str = "generator",
    ) -> str:
        """Send a chat completion request and return the response text."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self._resolve_tokens(max_tokens, role),
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"LLM API error {exc.code} for {self.model}:\n{detail[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Cannot reach {self.base_url} — is your local API server running?\n{exc}"
            ) from exc

        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(
                f"Unexpected LLM response structure: {json.dumps(body, indent=2)[:500]}"
            ) from exc

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        role: str = "generator",
    ) -> str:
        """Streamed version of chat(). Prints tokens as they arrive via SSE."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self._resolve_tokens(max_tokens, role),
            "stream": True,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)

        full_text = ""
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk_data = json.loads(data_str)
                            delta = chunk_data["choices"][0]["delta"].get("content", "")
                            if delta:
                                sys.stdout.write(delta)
                                sys.stdout.flush()
                                full_text += delta
                        except (KeyError, json.JSONDecodeError):
                            pass
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"LLM API error {exc.code} for {self.model}:\n{detail[:500]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Cannot reach {self.base_url} — is your local API server running?\n{exc}"
            ) from exc

        return full_text

    @staticmethod
    def _resolve_tokens(requested: int, role: str) -> int:
        """In --fast mode, apply the tighter per-role cap to cut generation time."""
        if FAST_MODE and role in FAST_MAX_TOKENS:
            return min(requested, FAST_MAX_TOKENS[role])
        return requested


# =========================================================================
# Crush CLI backend
# =========================================================================
class CrushClient:
    """LLM client that delegates to the Crush CLI (crush run)."""

    def __init__(self, model: str = "") -> None:
        self.bin = CRUSH_BIN

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        vrole: str = "generator",
    ) -> str:
        """Combine messages into a prompt and pipe to crush run."""
        prompt_parts: list[str] = []
        for m in messages:
            role = m["role"]
            content = m["content"]
            if role == "system":
                prompt_parts.append(f"[System instructions]\n{content}")
            elif role == "user":
                prompt_parts.append(f"[User]\n{content}")
            elif role == "assistant":
                prompt_parts.append(f"[Assistant]\n{content}")
        prompt = "\n\n".join(prompt_parts)

        proc = subprocess.run(
            [self.bin, "run"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.stdout.strip()

    def chat_stream(self, *args, **kwargs) -> str:
        """Periodically flush accumulated output while the sync subprocess runs."""
        import threading

        result: list[str] = [""]
        done: list[bool] = [False]

        def _run() -> None:
            result[0] = self.chat(*args, **kwargs)
            done[0] = True

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        # Show progress dots every 250ms while waiting
        dots = 0
        while not done[0]:
            thread.join(timeout=0.25)
            if done[0]:
                break
            sys.stdout.write(".")
            sys.stdout.flush()
            dots += 1
            if dots >= 60:
                sys.stdout.write("\n")
                sys.stdout.flush()
                dots = 0

        thread.join()
        full_text = result[0]

        # Erase dots, then stream out the full response
        if dots > 0:
            sys.stdout.write("\b" * dots + " " * dots + "\b" * dots)
            sys.stdout.flush()
        sys.stdout.write(full_text)
        sys.stdout.flush()
        return full_text


# =========================================================================
# Helper — build a summary of discovered files for the LLM prompt
# =========================================================================


def _file_summary(state: WorkspaceState) -> str:
    """Format discovered-file metadata into a compact prompt block,
    including import/export analysis for Python files."""
    lines: list[str] = []
    for df in state.discovered_files:
        size_kb = df.size / 1024
        entry = f"  • {df.path}  ({size_kb:.1f} KB, {df.extension})"
        if df.sample:
            fmt = df.sample.get("format", "?")
            entry += f"  [{fmt}]"
            # Show a preview snippet for text-based files
            preview = df.sample.get("preview") or df.sample.get("rows") or df.sample.get("sample")
            if preview:
                if isinstance(preview, list):
                    snippet = "\n".join(str(r) for r in preview[:5])
                else:
                    snippet = str(preview)[:300]
                entry += f"\n    sample:\n{textwrap.indent(snippet, '      ')}"

            # Include import lines for Python files
            if df.extension in (".py",):
                imports = df.sample.get("imports")
                if imports:
                    entry += f"\n    imports: {', '.join(imports)}"

        lines.append(entry)
    return "\n".join(lines)


def _prompt(prompt: str) -> str:
    """Apply --fast transformations: drop the chain-of-thought block so the
    model emits the answer directly (roughly halves generated tokens)."""
    if not FAST_MODE:
        return prompt
    # Remove lines that instruct the model to reason inside <reasoning> tags.
    out = []
    for line in prompt.split("\n"):
        if "<reasoning>" in line or "</reasoning>" in line:
            continue
        if "think through" in line.lower() or "before writing" in line.lower():
            continue
        if "before proposing" in line.lower() or "before writing a fix" in line.lower():
            continue
        out.append(line)
    return "\n".join(out)


# =========================================================================
# Policy: my_planner
# =========================================================================


def my_planner(goal: str, state: WorkspaceState) -> str:
    """Analyse discovered files and produce a build plan via LLM."""
    client = get_client_for("planner")
    model_display = _model_for_role("planner")
    summary = _file_summary(state)

    prompt = textwrap.dedent(f"""
    Analyze the user goal and workspace below. Before writing the plan,
    think through the approach step by step inside <reasoning> tags.

    GOAL:
    {goal}

    WORKSPACE FILES:
    {summary}

    <reasoning>
    1. What does the goal actually require? (new script? modify existing? analysis?)
    2. Which files in the workspace are relevant to the goal?
    3. What's the simplest approach that solves the problem?
    4. What inputs/outputs will the script need?
    5. How should it be tested?
    </reasoning>

    After your reasoning, output the plan as a numbered list covering:
    • what file(s) to create (one script unless the goal demands more)
    • what the script should do — inputs, logic, outputs
    • which Python standard-library modules to use
    • what test(s) should pass to verify it works
    """)
    prompt = _prompt(prompt)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a precise senior software architect. "
                "Always think through the problem before proposing a solution. "
                "Prefer simple, correct designs over clever ones. "
                "Output reasoning then a numbered plan."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    print(f"\n  {icon('brain')}  Planner ({model_display})")
    try:
        if STREAM_OUTPUT:
            plan = client.chat_stream(messages, role="planner")
        else:
            plan = client.chat(messages, role="planner")
        print()
        return plan.strip()
    except (RuntimeError, Exception) as exc:
        fallback_model = _fallback_model_for_role("planner")
        if fallback_model:
            print(f"\n  [!] Planner failed, using fallback model: {fallback_model}")
            try:
                fb_client = _make_fallback_client("planner", fallback_model)
                if STREAM_OUTPUT:
                    plan = fb_client.chat_stream(messages, role="planner")
                else:
                    plan = fb_client.chat(messages, role="planner")
                print()
                return plan.strip()
            except (RuntimeError, Exception) as exc2:
                print(f"  [!] Fallback also failed: {exc2}")
        print(f"  [!] Planner failed — returning minimal plan ({exc})")
        return f"## Plan (fallback — LLM unavailable)\n\n1. Create a Python script to accomplish: {goal}\n"


# =========================================================================
# Policy: my_generator
# =========================================================================


def my_generator(
    plan: str,
    state: WorkspaceState,
    registry: ToolRegistry,
    env: AgentEnvironment,
) -> list[tuple[str, str]]:
    """Generate code from the plan using the LLM."""
    client = get_client_for("generator")
    model_display = _model_for_role("generator")
    summary = _file_summary(state)

    prompt = textwrap.dedent(f"""
    Implement the plan below. Before writing code, reason through
    the design inside <reasoning> tags.

    PLAN:
    {plan}

    WORKSPACE FILES (for reference):
    {summary}

    <reasoning>
    1. What's the core algorithm or structure needed?
    2. What are the edge cases and error conditions?
    3. What's the cleanest way to structure the code?
    4. Which stdlib modules are appropriate?
    5. How will the tests verify correctness?
    </reasoning>

    Output exactly one file block in this format:

    FILE: <filename>
    ```python
    <code>
    ```

    QUALITY STANDARDS:
    • Include type hints on all function signatures
    • Write docstrings for every function and class (Google style)
    • Handle edge cases (empty input, malformed data, permissions)
    • Use descriptive variable names, not single letters
    • Keep functions small and focused (one job per function)
    • Include `if __name__ == "__main__":` guard
    • Exit with code 0 on success, non-zero on failure
    • Use ONLY Python standard library — no pip installs
    • Read/write files relative to the current working directory
    """)
    prompt = _prompt(prompt)

    print(f"\n  {icon('code')}  Generator ({model_display})")
    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior Python engineer writing production-quality code. "
                "Think through the design before writing. "
                "Every function gets type hints and a docstring. "
                "Handle errors gracefully. Be concise but correct."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    try:
        if STREAM_OUTPUT:
            code = client.chat_stream(messages, role="generator")
        else:
            code = client.chat(messages, role="generator")
        print()
    except (RuntimeError, Exception) as exc:
        fallback_model = _fallback_model_for_role("generator")
        if fallback_model:
            print(f"\n  [!] Generator failed, using fallback model: {fallback_model}")
            try:
                fb_client = _make_fallback_client("generator", fallback_model)
                if STREAM_OUTPUT:
                    code = fb_client.chat_stream(messages, role="generator")
                else:
                    code = fb_client.chat(messages, role="generator")
                print()
            except (RuntimeError, Exception) as exc2:
                print(f"  [!] Fallback also failed: {exc2}")
                return []
        else:
            print(f"  [!] Generator failed ({exc}) — returning empty")
            return []

    # Parse the FILE: … ```python … ``` block
    files = _parse_file_blocks(code)

    if not files:
        # Fallback: treat the entire response as one script
        fallback_name = "generated_script.py"
        print(f"  [WARN]  No FILE: block found — writing {fallback_name}")
        files = [(fallback_name, code.strip())]

    return files


_BLOCK_RE = re.compile(
    r"FILE:\s*(\S+)\s*\n"
    r"```(?:python)?\s*\n"
    r"(.*?)"
    r"\n\s*```",
    re.DOTALL | re.IGNORECASE,
)


def _parse_file_blocks(text: str) -> list[tuple[str, str]]:
    """Extract ``FILE: path\\n```python\\n...\\n````` blocks from LLM output."""
    matches = _BLOCK_RE.findall(text)
    if matches:
        return [(fname, code.strip()) for fname, code in matches]
    return []


# =========================================================================
# Policy: my_fixer
# =========================================================================


def my_fixer(
    log: TestLog,
    state: WorkspaceState,
    registry: ToolRegistry,
    env: AgentEnvironment,
) -> list[tuple[str, str, str]] | None:
    """Analyse a test failure and produce patches via the LLM."""
    client = get_client_for("fixer")
    model_display = _model_for_role("fixer")

    # Find the code that failed
    failed_code = ""
    for gf in state.generated_files:
        if gf.path == log.file:
            failed_code = gf.content
            break

    if not failed_code:
        # Try reading from disk
        try:
            failed_code = Path(log.file).read_text(encoding="utf-8")
        except Exception:
            pass

    prompt = textwrap.dedent(f"""
    A Python script failed during testing. Analyse the root cause
    before producing patches. Think step-by-step inside <reasoning> tags.

    FILE: {log.file}

    ERROR (exit code {log.returncode}):
    {log.stderr[:2000]}

    CURRENT CODE:
    ```python
    {failed_code}
    ```

    <reasoning>
    1. What is the error telling us? (traceback line, exception type, message)
    2. What was the code trying to do at that point?
    3. What's the root cause? (logic bug? wrong API? missing import? type error?)
    4. What's the minimal change that fixes it without breaking other things?
    5. Are there related issues in the same area of code?
    </reasoning>

    After reasoning, output patches in this exact format:

    PATCH: {log.file}
    ---OLD---
    <exact text to replace — copy verbatim from CURRENT CODE>
    ---NEW---
    <replacement text>

    Repeat the PATCH: block for each change you make.
    Keep patches minimal — one or two focused edits are better than rewriting.
    If no fix is possible, output: NO_FIX
    """)
    prompt = _prompt(prompt)

    print(f"\n  {icon('fix')}  Fixer ({model_display})")
    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior debugging engineer. "
                "Always diagnose the root cause before writing a fix. "
                "Make minimal, precise patches — don't rewrite unrelated code. "
                "Verify your fix would actually resolve the error."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    try:
        if STREAM_OUTPUT:
            answer = client.chat_stream(messages, role="fixer")
        else:
            answer = client.chat(messages, role="fixer")
        print()
    except (RuntimeError, Exception) as exc:
        fallback_model = _fallback_model_for_role("fixer")
        if fallback_model:
            print(f"\n  [!] Fixer failed, using fallback model: {fallback_model}")
            try:
                fb_client = _make_fallback_client("fixer", fallback_model)
                if STREAM_OUTPUT:
                    answer = fb_client.chat_stream(messages, role="fixer")
                else:
                    answer = fb_client.chat(messages, role="fixer")
                print()
            except (RuntimeError, Exception) as exc2:
                print(f"  [!] Fallback also failed: {exc2}")
                return None
        else:
            print(f"  [!] Fixer failed ({exc}) — skipping")
            return None

    if answer.strip().upper().startswith("NO_FIX"):
        return None

    return _parse_patches(answer)


_PATCH_RE = re.compile(
    r"PATCH:\s*(\S+)\s*\n"
    r"---OLD---\s*\n"
    r"(.*?)"
    r"\n---NEW---\s*\n"
    r"(.*?)(?=\nPATCH:|\Z)",
    re.DOTALL,
)


def _parse_patches(text: str) -> list[tuple[str, str, str]]:
    """Extract ``PATCH: path\\n---OLD---\\n...\\n---NEW---\\n...`` blocks."""
    patches: list[tuple[str, str, str]] = []
    for match in _PATCH_RE.finditer(text):
        fpath = match.group(1).strip()
        old = match.group(2).strip()
        new = match.group(3).strip()
        patches.append((fpath, old, new))
    return patches if patches else []


# =========================================================================
# Bootstrap
# =========================================================================


def _check_api() -> bool:
    """Quick health-check: is the LLM API reachable?"""
    url = f"{LLM_BASE_URL.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m.get("id", "?") for m in data.get("data", [])]
            print(f"  [API]  {LLM_BASE_URL}  models: {', '.join(models[:6])}")
            return True
    except Exception:
        print(f"  [API]  {LLM_BASE_URL}  (not reachable — continuing anyway)")
        return False


def main() -> None:
    print_logo()
    _ensure_router_loaded()
    if ROUTER_CONFIG:
        for role in ("planner", "generator", "fixer"):
            if role in ROUTER_CONFIG:
                p, m = ROUTER_CONFIG[role]
                print(f"  Router  {role:>9}: {p}/{m}")
    else:
        print(f"  Planner   model: {MODEL_PLANNER}")
        print(f"  Generator model: {MODEL_GENERATOR}")
        print(f"  Fixer     model: {MODEL_FIXER}")
    print(f"  API       endpoint: {LLM_BASE_URL}")
    print()

    _check_api()
    print()

    # -- Infrastructure ------------------------------------------------
    print("  [BOOT] Setting up agent environment …")
    env = AgentEnvironment(base_path=str(HERE))
    if env.is_ready:
        env.teardown()
    env.setup()
    print(f"  [BOOT]  agent_env ready at {env.python}")

    registry = ToolRegistry()
    registry.register_defaults(env)

    orch = Orchestrator(
        env,
        registry,
        base_path=str(HERE),
        workspace_excludes=[
            "agent_env",
            ".crush",
            ".git",
            "__pycache__",
            ".mypy_cache",
        ],
    )

    # -- Goal ----------------------------------------------------------
    goal = (
        "Scan for mock_logs.txt in the workspace, extract its data "
        "structure, and write a Python script that parses the log file "
        "and extracts only the lines containing ERROR or CRITICAL markers "
        "into a clean summary file named summary_output.txt."
    )

    # -- Run -----------------------------------------------------------
    print()
    state = orch.run(
        goal=goal,
        planner=my_planner,
        code_gen=my_generator,
        fixer=my_fixer,
        max_iterations=3,
    )

    # -- Report --------------------------------------------------------
    print()
    print("=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Phase:          {state.phase}")
    print(f"  Files generated: {len(state.generated_files)}")
    for gf in state.generated_files:
        status = "PASS" if gf.passed else "FAIL"
        print(f"    {gf.path:30s}  [{status}]  (iteration {gf.iteration})")
    print(f"  WTF iterations: {state.iteration}")
    print(f"  Loop passed:    {state.loop_passed}")
    print(f"  Test logs:      {len(state.test_logs)}")

    # Show summary if produced
    summary_path = HERE / "summary_output.txt"
    if summary_path.exists():
        print()
        print("  --- summary_output.txt ---")
        content = summary_path.read_text().strip()
        print(textwrap.indent(content, "  "))
        summary_path.unlink()

    # Cleanup generated files
    for gf in state.generated_files:
        p = HERE / gf.path
        p.unlink(missing_ok=True)
        (HERE / (gf.path + ".bak")).unlink(missing_ok=True)
    env.teardown()

    print()
    if state.loop_passed:
        print("  [PASS]  End-to-end LLM run succeeded.")
        print(f"  Plan summary: {state.plan[:120]}…")
    else:
        print("  [FAIL]  End-to-end LLM run did not converge.")
        sys.exit(1)


if __name__ == "__main__":
    main()
