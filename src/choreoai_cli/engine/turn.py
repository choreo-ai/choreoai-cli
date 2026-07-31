"""Turn / loop state: named continue and terminal outcomes.

Makes budgets, aborts, and completion legible instead of ad-hoc flags.
The actual LLM tool loop still lives in choreoai's LLMAgent; this names the
outer harness-level outcomes.
"""

from __future__ import annotations

from enum import Enum


class TurnOutcome(str, Enum):
    """Named result of one agent turn (or a mid-loop control signal)."""

    # Continue-style (informational; loop proceeds)
    NEXT_TURN = "next_turn"
    TOOL_USE = "tool_use"

    # Terminal outcomes
    COMPLETED = "completed"
    ABORTED = "aborted"
    BUDGET_EXCEEDED = "budget_exceeded"
    MAX_TURNS = "max_turns"
    ERROR = "error"


def is_terminal(outcome: TurnOutcome) -> bool:
    """Return True if the outcome ends the current turn."""
    return outcome in {
        TurnOutcome.COMPLETED,
        TurnOutcome.ABORTED,
        TurnOutcome.BUDGET_EXCEEDED,
        TurnOutcome.MAX_TURNS,
        TurnOutcome.ERROR,
    }
