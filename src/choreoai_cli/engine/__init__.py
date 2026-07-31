"""Agent harness / query engine package."""

from choreoai_cli.engine.events import (
    AnswerChunk,
    LlmCallEvent,
    ToolCallEvent,
    TurnEvent,
    TurnFinished,
    TurnStarted,
    TurnStats,
    adapt_choreoai_event,
)
from choreoai_cli.engine.mock_model import DemoChatModel, make_demo_model
from choreoai_cli.engine.query_engine import (
    CODING_SYSTEM_PROMPT,
    DEFAULT_STEP_BUDGET,
    CodingHarness,
    QueryEngine,
    RunResult,
)
from choreoai_cli.engine.turn import TurnOutcome, is_terminal

__all__ = [
    "CODING_SYSTEM_PROMPT",
    "DEFAULT_STEP_BUDGET",
    "AnswerChunk",
    "CodingHarness",
    "DemoChatModel",
    "LlmCallEvent",
    "QueryEngine",
    "RunResult",
    "ToolCallEvent",
    "TurnEvent",
    "TurnFinished",
    "TurnOutcome",
    "TurnStarted",
    "TurnStats",
    "adapt_choreoai_event",
    "is_terminal",
    "make_demo_model",
]
