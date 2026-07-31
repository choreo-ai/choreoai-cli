"""Typed turn / UI event model.

Thin adapters over choreoai's event stream so the UI (and tests) subscribe to a
stable, named set of events instead of raw framework types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from choreoai_cli.engine.turn import TurnOutcome


@dataclass
class TurnEvent:
    """Base class for all turn-scoped UI events."""

    kind: str = ""


@dataclass
class TurnStarted(TurnEvent):
    kind: str = "started"
    prompt: str = ""


@dataclass
class ToolCallEvent(TurnEvent):
    """A tool finished (success or failure) — card-ready payload."""

    kind: str = "tool_call"
    tool_name: str = "?"
    success: bool = False
    duration_ms: float | int | None = None
    arg_summary: str | None = None
    result_preview: str | None = None
    error: str | None = None


@dataclass
class LlmCallEvent(TurnEvent):
    kind: str = "llm_call"
    model: str = "model"
    success: bool = True
    duration_ms: float | int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None


@dataclass
class AnswerChunk(TurnEvent):
    """Token / answer fragment (reserved for future true streaming)."""

    kind: str = "answer_chunk"
    text: str = ""


@dataclass
class TurnFinished(TurnEvent):
    kind: str = "finished"
    outcome: TurnOutcome = TurnOutcome.COMPLETED
    output: Any = None
    error: str | None = None
    run_id: str = ""


@dataclass
class TurnStats:
    """Accumulated counters for one agent turn (footer / toolbar)."""

    tool_count: int = 0
    llm_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    steps: int = 0

    def reset(self) -> None:
        self.tool_count = 0
        self.llm_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.steps = 0


def adapt_choreoai_event(event: Any, *, stats: TurnStats | None = None) -> TurnEvent | None:
    """Map a choreoai core Event into a typed TurnEvent (or None if uninteresting)."""
    etype = getattr(event, "type", None)

    if etype == "tool_called":
        tool_name = getattr(event, "tool_name", "?") or "?"
        ok = bool(getattr(event, "success", False))
        ms = getattr(event, "duration_ms", None)
        err = getattr(event, "error", None)
        meta = getattr(event, "metadata", None) or {}
        arg_summary: str | None = None
        result_preview: str | None = None
        if isinstance(meta, dict):
            for key in ("args_summary", "input_summary"):
                val = meta.get(key)
                if val:
                    arg_summary = str(val)
                    break
            for key in ("result_summary", "output_summary"):
                val = meta.get(key)
                if val:
                    result_preview = str(val)
                    break
        if stats is not None:
            stats.tool_count += 1
        return ToolCallEvent(
            tool_name=tool_name,
            success=ok,
            duration_ms=ms,
            arg_summary=arg_summary,
            result_preview=result_preview,
            error=str(err) if err else None,
        )

    if etype == "llm_called":
        in_tok = getattr(event, "input_tokens", None)
        out_tok = getattr(event, "output_tokens", None)
        if stats is not None:
            stats.llm_count += 1
            if isinstance(in_tok, int):
                stats.total_input_tokens += in_tok
            if isinstance(out_tok, int):
                stats.total_output_tokens += out_tok
        return LlmCallEvent(
            model=getattr(event, "model", None) or "model",
            success=bool(getattr(event, "success", True)),
            duration_ms=getattr(event, "duration_ms", None),
            input_tokens=in_tok if isinstance(in_tok, int) else None,
            output_tokens=out_tok if isinstance(out_tok, int) else None,
            error=str(getattr(event, "error", None) or "") or None,
        )

    if etype == "step_finished":
        if stats is not None:
            stats.steps += 1
        return None

    if etype == "run_started":
        return None  # TurnStarted is emitted by QueryEngine

    if etype == "run_finished":
        return None  # TurnFinished is emitted by QueryEngine

    return None
