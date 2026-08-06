"""
virgo_selfheal — Self-Healing Pipeline engine.

When the fixer fails repeatedly (default: 3+ failures on the same file),
this engine:
  1. Searches the web for the error (DuckDuckGo)
  2. Fetches relevant pages for solutions
  3. Feeds the research back to the fixer as enhanced context
  4. Tracks healing attempts and success rate

Usage (CLI):
    from virgo_selfheal import SelfHealEngine
    engine = SelfHealEngine(llm_client, web_search_fn)
    result = engine.heal(log, state, failed_code)
    if result.recovered:
        print("Self-healed!")

Usage (GUI):
    engine = SelfHealEngine(llm_client, web_search_fn)
    engine.on_research = lambda r: self._update_healing_ui(r)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from _console import icon


@dataclass
class ResearchResult:
    """A single web search + fetch result."""
    query: str
    url: str
    title: str
    snippet: str
    fetched: bool = False
    content: str = ""


@dataclass
class HealAttempt:
    """One self-healing attempt."""
    file: str
    error: str
    iteration: int
    research: list[ResearchResult]
    fixer_prompt: str        # the enhanced prompt sent to the fixer
    fixer_response: str      # what the fixer returned
    recovered: bool          # did the fix work?
    duration: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class HealResult:
    """Outcome of the self-healing process."""
    file: str
    attempts: list[HealAttempt]
    recovered: bool
    total_research: int
    total_duration: float

    @property
    def summary(self) -> str:
        status = "RECOVERED" if self.recovered else "UNRECOVERABLE"
        return (
            f"Self-heal [{status}]: {self.file}\n"
            f"  Research items: {self.total_research}\n"
            f"  Attempts: {len(self.attempts)}\n"
            f"  Duration: {self.total_duration:.1f}s"
        )


class SelfHealEngine:
    """Detects repeated failures and researches solutions via web search.

    Parameters
    ----------
    llm_client:
        Object with `.chat(messages, temperature, max_tokens)` method.
    web_search_fn:
        Callable(query) -> dict with {"status": "success", "results": [...]}.
        Typically virgo_web_search.web_search or google_search.
    web_fetch_fn:
        Optional callable(url) -> str that fetches page content.
    failure_threshold:
        Number of consecutive failures before triggering self-heal.
    max_research_items:
        Maximum web results to fetch per attempt.
    """

    def __init__(
        self,
        llm_client: Any = None,
        web_search_fn: Callable[[str], dict] | None = None,
        web_fetch_fn: Callable[[str], str] | None = None,
        failure_threshold: int = 3,
        max_research_items: int = 3,
    ) -> None:
        self.llm = llm_client
        self.web_search = web_search_fn
        self.web_fetch = web_fetch_fn
        self.failure_threshold = failure_threshold
        self.max_research_items = max_research_items

        # Tracking
        self._failure_counts: dict[str, int] = {}  # file -> consecutive failures
        self.attempts: list[HealAttempt] = []
        self.on_research: Callable[[ResearchResult], None] | None = None
        self.on_heal_attempt: Callable[[HealAttempt], None] | None = None

    def should_heal(self, file: str) -> bool:
        """Return True if this file has hit the failure threshold."""
        return self._failure_counts.get(file, 0) >= self.failure_threshold

    def record_failure(self, file: str) -> int:
        """Record a failure for a file. Returns the new count."""
        self._failure_counts[file] = self._failure_counts.get(file, 0) + 1
        return self._failure_counts[file]

    def record_success(self, file: str) -> None:
        """Reset failure count for a file (it's fixed)."""
        self._failure_counts.pop(file, None)

    def heal(
        self,
        file: str,
        error: str,
        iteration: int,
        failed_code: str,
        *,
        existing_patches: str = "",
    ) -> HealResult:
        """Research the error and attempt to generate a fix.

        This method:
        1. Searches the web for the error
        2. Fetches the most promising results
        3. Builds an enhanced fixer prompt with research context
        4. Calls the LLM fixer with the enhanced prompt
        5. Returns the result for the caller to apply

        Returns a HealResult — the caller must check .recovered and
        apply any patches themselves.
        """
        t0 = time.time()
        attempts: list[HealAttempt] = []

        # ── Step 1: Research the error ─────────────────────────────
        research = self._research_error(error, file)

        # ── Step 2: Build enhanced prompt ──────────────────────────
        research_block = self._format_research(research)
        enhanced_prompt = self._build_heal_prompt(
            file, error, failed_code, research_block, existing_patches
        )

        # ── Step 3: Call the fixer ─────────────────────────────────
        fixer_response = ""
        recovered = False

        if self.llm:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a senior debugging engineer with access to "
                        "web research. The standard fixer has failed multiple "
                        "times. Use the research context below to find a "
                        "solution the fixer missed. Be creative but precise."
                    ),
                },
                {"role": "user", "content": enhanced_prompt},
            ]

            try:
                fixer_response = self.llm.chat(
                    messages, temperature=0.3, max_tokens=4096, role="fixer"
                )
                # Check if the fixer produced valid patches
                if "NO_FIX" not in fixer_response and "PATCH:" in fixer_response:
                    recovered = True
            except Exception as exc:
                fixer_response = f"[Self-heal LLM error: {exc}]"

        attempt = HealAttempt(
            file=file,
            error=error,
            iteration=iteration,
            research=research,
            fixer_prompt=enhanced_prompt,
            fixer_response=fixer_response,
            recovered=recovered,
            duration=time.time() - t0,
        )
        attempts.append(attempt)
        self.attempts.append(attempt)

        if self.on_heal_attempt:
            try:
                self.on_heal_attempt(attempt)
            except Exception:
                pass

        return HealResult(
            file=file,
            attempts=attempts,
            recovered=recovered,
            total_research=len(research),
            total_duration=time.time() - t0,
        )

    def _research_error(self, error: str, file: str) -> list[ResearchResult]:
        """Search the web for the error and fetch promising results."""
        if not self.web_search:
            return []

        # Build a focused search query from the error
        query = self._error_to_query(error, file)

        try:
            search_result = self.web_search(query)
        except Exception:
            return []

        if search_result.get("status") != "success":
            return []

        results: list[ResearchResult] = []
        for item in search_result.get("results", [])[:self.max_research_items]:
            rr = ResearchResult(
                query=query,
                url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
            )

            # Try to fetch the page content
            if self.web_fetch and rr.url:
                try:
                    rr.content = self.web_fetch(rr.url)[:3000]  # cap at 3KB
                    rr.fetched = True
                except Exception:
                    pass

            results.append(rr)

            if self.on_research:
                try:
                    self.on_research(rr)
                except Exception:
                    pass

        return results

    def _error_to_query(self, error: str, file: str) -> str:
        """Convert an error message into a web search query."""
        lines = error.strip().splitlines()

        # Find the most informative line (traceback, exception, etc.)
        key_line = ""
        for line in reversed(lines):
            line = line.strip()
            if any(kw in line.lower() for kw in [
                "error", "exception", "traceback", "typeerror",
                "valueerror", "importerror", "attributeerror",
                "filenotfound", "syntaxerror", "nameerror",
                "module", "has no attribute",
            ]):
                key_line = line
                break

        if not key_line and lines:
            key_line = lines[-1].strip()

        # Clean up the line for search
        key_line = key_line[:120]  # cap length
        # Add "python" to narrow results
        return f"python {key_line} fix"

    def _format_research(self, research: list[ResearchResult]) -> str:
        """Format research results into a context block for the LLM."""
        if not research:
            return "No web research available."

        parts = ["WEB RESEARCH (from DuckDuckGo search):"]
        for i, rr in enumerate(research, 1):
            parts.append(f"\n--- Result {i}: {rr.title} ---")
            parts.append(f"URL: {rr.url}")
            parts.append(f"Snippet: {rr.snippet}")
            if rr.fetched and rr.content:
                parts.append(f"Page content (excerpt):\n{rr.content[:2000]}")

        return "\n".join(parts)

    def _build_heal_prompt(
        self,
        file: str,
        error: str,
        failed_code: str,
        research_block: str,
        existing_patches: str,
    ) -> str:
        """Build the enhanced fixer prompt with research context."""
        return f"""A Python script has failed 3+ times and the standard fixer
cannot resolve it. You have web research to help find a solution.

FILE: {file}

ERROR:
{error[:2000]}

CURRENT CODE:
```python
{failed_code[:4000]}
```

{research_block}

{f'PREVIOUS FAILED PATCHES (do not repeat these):' if existing_patches else ''}
{existing_patches}

Based on the error AND the web research, produce a fix. Think about:
1. What do the web results suggest about this error?
2. Is there an API change, missing dependency, or version mismatch?
3. What's the minimal change that would fix this?

Output patches in this exact format:
PATCH: {file}
---OLD---
<exact text to replace>
---NEW---
<replacement text>

If no fix is possible, output: NO_FIX"""

    def get_stats(self) -> dict[str, Any]:
        """Return healing statistics."""
        total = len(self.attempts)
        recovered = sum(1 for a in self.attempts if a.recovered)
        return {
            "total_attempts": total,
            "recovered": recovered,
            "success_rate": recovered / total if total > 0 else 0.0,
            "files_healed": len(set(a.file for a in self.attempts if a.recovered)),
            "total_research_items": sum(len(a.research) for a in self.attempts),
        }

    def clear(self) -> None:
        """Reset all tracking state."""
        self._failure_counts.clear()
        self.attempts.clear()
