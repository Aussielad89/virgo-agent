"""
virgo_debate — Agent-to-Agent Debate engine.

Two LLM agents argue different implementation approaches:
  • Performer   — advocates for the direct, practical solution
  • Critic      — challenges assumptions, suggests alternatives

The user (or auto-mode) picks the winning approach. The debate is
structured in 2 rounds with a final verdict.

Usage (CLI):
    from virgo_debate import DebateEngine
    engine = DebateEngine(llm_client)
    result = engine.debate(goal, context)
    print(result.winner)
    print(result.winner_approach)

Usage (GUI):
    engine = DebateEngine(llm_client)
    engine.on_round = lambda r: self._update_debate_ui(r)
    result = engine.debate(goal, context)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from _console import icon


@dataclass
class DebateRound:
    """One round of argumentation from one agent."""
    agent: str          # "performer" or "critic"
    role: str           # display name
    argument: str       # the argument text
    approach: str       # the proposed approach (concise)
    round_num: int      # 1 or 2
    timestamp: float = field(default_factory=time.time)


@dataclass
class DebateResult:
    """Final outcome of a debate."""
    goal: str
    rounds: list[DebateRound]
    winner: str         # "performer" or "critic"
    winner_approach: str
    winner_argument: str
    loser_argument: str
    auto_picked: bool   # True if user didn't choose (auto-judge)
    duration: float = 0.0

    @property
    def summary(self) -> str:
        tag = "AUTO" if self.auto_picked else "USER"
        return (
            f"Debate winner: {self.winner.upper()} [{tag}]\n"
            f"Approach: {self.winner_approach}\n"
            f"Duration: {self.duration:.1f}s"
        )


class DebateEngine:
    """Orchestrates a structured debate between two LLM personas.

    Parameters
    ----------
    llm_client:
        An object with a `.chat(messages, temperature, max_tokens)` method.
        Usually an LLMClient or CrushClient from main.py.
    auto_judge:
        If True, a third LLM call decides the winner (no user input).
    """

    def __init__(
        self,
        llm_client: Any = None,
        auto_judge: bool = False,
    ) -> None:
        self.llm = llm_client
        self.auto_judge = auto_judge
        self.on_round: Callable[[DebateRound], None] | None = None
        self.on_result: Callable[[DebateResult], None] | None = None

    def debate(
        self,
        goal: str,
        context: str = "",
        *,
        max_tokens: int = 2048,
    ) -> DebateResult:
        """Run a 2-round debate and return the result.

        Parameters
        ----------
        goal:
            The implementation task being debated.
        context:
            Additional context (existing code, error logs, etc.).
        """
        t0 = time.time()
        rounds: list[DebateRound] = []

        # ── Round 1: Opening arguments ─────────────────────────────
        performer_r1 = self._get_argument(
            agent="performer",
            goal=goal,
            context=context,
            round_num=1,
            prior_rounds=[],
            max_tokens=max_tokens,
        )
        rounds.append(performer_r1)
        self._emit_round(performer_r1)

        critic_r1 = self._get_argument(
            agent="critic",
            goal=goal,
            context=context,
            round_num=1,
            prior_rounds=[performer_r1],
            max_tokens=max_tokens,
        )
        rounds.append(critic_r1)
        self._emit_round(critic_r1)

        # ── Round 2: Rebuttals ─────────────────────────────────────
        performer_r2 = self._get_argument(
            agent="performer",
            goal=goal,
            context=context,
            round_num=2,
            prior_rounds=[performer_r1, critic_r1],
            max_tokens=max_tokens,
        )
        rounds.append(performer_r2)
        self._emit_round(performer_r2)

        critic_r2 = self._get_argument(
            agent="critic",
            goal=goal,
            context=context,
            round_num=2,
            prior_rounds=[performer_r1, critic_r1, performer_r2],
            max_tokens=max_tokens,
        )
        rounds.append(critic_r2)
        self._emit_round(critic_r2)

        # ── Verdict ────────────────────────────────────────────────
        winner, winner_approach, auto_picked = self._judge(
            goal, rounds, max_tokens=max_tokens
        )

        winner_rounds = [r for r in rounds if r.agent == winner]
        loser_rounds = [r for r in rounds if r.agent != winner]

        result = DebateResult(
            goal=goal,
            rounds=rounds,
            winner=winner,
            winner_approach=winner_rounds[0].approach if winner_rounds else "",
            winner_argument=winner_rounds[-1].argument if winner_rounds else "",
            loser_argument=loser_rounds[-1].argument if loser_rounds else "",
            auto_picked=auto_picked,
            duration=time.time() - t0,
        )

        if self.on_result:
            try:
                self.on_result(result)
            except Exception:
                pass

        return result

    def _get_argument(
        self,
        agent: str,
        goal: str,
        context: str,
        round_num: int,
        prior_rounds: list[DebateRound],
        max_tokens: int,
    ) -> DebateRound:
        """Get an argument from one agent for one round."""
        if agent == "performer":
            system = (
                "You are the PERFORMER — a senior engineer who advocates for "
                "the most direct, practical implementation. You value speed, "
                "simplicity, and getting things working. You prefer proven "
                "patterns over clever abstractions. Be specific with code "
                "structures and concrete implementation details."
            )
            role_name = "Performer"
        else:
            system = (
                "You are the CRITIC — a senior architect who challenges "
                "assumptions and proposes alternative approaches. You value "
                "correctness, maintainability, and long-term design. You "
                "question shortcuts and propose more robust solutions. Be "
                "specific with trade-offs and architectural reasoning."
            )
            role_name = "Critic"

        # Build the prompt with prior arguments
        history = ""
        for pr in prior_rounds:
            tag = "PERFORMER" if pr.agent == "performer" else "CRITIC"
            history += f"\n--- {tag} (Round {pr.round_num}) ---\n{pr.argument}\n"

        if round_num == 1:
            prompt = f"""Debate the best implementation approach for:

GOAL: {goal}

{f'CONTEXT: {context}' if context else ''}

Propose your approach. Be specific about:
1. Architecture / structure
2. Key implementation steps
3. Why your approach is better

Output your argument, then on a new line starting with APPROACH: 
write a one-line summary of your proposed approach."""
        else:
            prompt = f"""Rebuttal round. Respond to the other agent's arguments:

GOAL: {goal}
{history}

Challenge or refine your position. Address their specific points.
Then on a new line starting with APPROACH: 
write your refined one-line summary."""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        try:
            answer = self.llm.chat(
                messages,
                temperature=0.5 if agent == "performer" else 0.7,
                max_tokens=max_tokens,
                role="debate",
            )
        except Exception as exc:
            answer = f"[Debate error: {exc}]"

        # Extract approach line
        approach = ""
        for line in answer.strip().splitlines():
            if line.upper().startswith("APPROACH:"):
                approach = line.split(":", 1)[1].strip()
                break

        return DebateRound(
            agent=agent,
            role=role_name,
            argument=answer,
            approach=approach or f"{role_name}'s approach (round {round_num})",
            round_num=round_num,
        )

    def _judge(
        self,
        goal: str,
        rounds: list[DebateRound],
        max_tokens: int,
    ) -> tuple[str, str, bool]:
        """Determine the winner. Returns (winner, approach, auto_picked)."""
        performer_args = "\n".join(
            f"Round {r.round_num}: {r.argument[:500]}"
            for r in rounds if r.agent == "performer"
        )
        critic_args = "\n".join(
            f"Round {r.round_num}: {r.argument[:500]}"
            for r in rounds if r.agent == "critic"
        )

        if self.auto_judge:
            # LLM judge
            judge_system = (
                "You are an impartial judge evaluating two implementation "
                "approaches. Be objective and pick the approach that best "
                "serves the goal. Consider: simplicity, correctness, "
                "maintainability, and risk."
            )
            judge_prompt = f"""GOAL: {goal}

PERFORMER argues:
{performer_args}

CRITIC argues:
{critic_args}

Which approach better serves the goal? Reply with exactly one word:
PERFORMER or CRITIC
Then on the next line, write a one-sentence justification."""

            messages = [
                {"role": "system", "content": judge_system},
                {"role": "user", "content": judge_prompt},
            ]

            try:
                verdict = self.llm.chat(
                    messages, temperature=0.2, max_tokens=256, role="judge"
                )
                first_word = verdict.strip().split()[0].upper().rstrip(".:")
                if first_word in ("PERFORMER", "PERFORMER'S"):
                    winner = "performer"
                elif first_word in ("CRITIC", "CRITIC'S"):
                    winner = "critic"
                else:
                    winner = "performer"  # default
            except Exception:
                winner = "performer"

            auto_picked = True
        else:
            # Interactive — ask user
            print(f"\n  {icon('debate')}  \033[1;35mDEBATE RESULTS\033[0m")
            print(f"  {'─' * 56}")
            print(f"  \033[1;36mPERFORMER\033[0m approach:")
            perf_approach = next(
                (r.approach for r in rounds if r.agent == "performer"), "N/A"
            )
            print(f"    → {perf_approach}")
            print(f"  \033[1;33mCRITIC\033[0m approach:")
            crit_approach = next(
                (r.approach for r in rounds if r.agent == "critic"), "N/A"
            )
            print(f"    → {crit_approach}")
            print(f"  {'─' * 56}")

            try:
                choice = input(
                    "  >>> Who wins? (p = Performer / c = Critic): "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "p"

            winner = "performer" if choice.startswith("p") else "critic"
            auto_picked = False

        winner_approach = next(
            (r.approach for r in rounds if r.agent == winner), ""
        )
        return winner, winner_approach, auto_picked

    def _emit_round(self, round: DebateRound) -> None:
        """Notify the GUI callback about a new round."""
        if self.on_round:
            try:
                self.on_round(round)
            except Exception:
                pass

    @staticmethod
    def format_round(round: DebateRound) -> str:
        """Format a debate round for terminal display."""
        color = "\033[1;36m" if round.agent == "performer" else "\033[1;33m"
        reset = "\033[0m"
        tag = "PERFORMER" if round.agent == "performer" else "CRITIC"
        return (
            f"\n  {color}{'═' * 56}{reset}\n"
            f"  {color}{tag}{reset} — Round {round.round_num}\n"
            f"  {color}{'─' * 56}{reset}\n"
            f"{round.argument}\n"
            f"  {color}Approach: {round.approach}{reset}\n"
        )
