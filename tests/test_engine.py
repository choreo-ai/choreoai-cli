"""Offline tests for QueryEngine, turn outcomes, and typed events."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from choreoai_cli.engine import (
    QueryEngine,
    TurnFinished,
    TurnOutcome,
    TurnStarted,
    is_terminal,
)
from choreoai_cli.tools.base import build_tool, get_tool_safety
from fakes import FakeChatModel
from pydantic import BaseModel, Field


class _EmptyIn(BaseModel):
    x: str = Field(default="")


def test_turn_outcome_terminal() -> None:
    assert is_terminal(TurnOutcome.COMPLETED)
    assert is_terminal(TurnOutcome.BUDGET_EXCEEDED)
    assert not is_terminal(TurnOutcome.TOOL_USE)
    assert not is_terminal(TurnOutcome.NEXT_TURN)


def test_build_tool_fail_closed_defaults() -> None:
    tool = build_tool(
        name="noop",
        description="noop",
        func=lambda x="": "ok",
        args_schema=_EmptyIn,
    )
    safety = get_tool_safety(tool)
    assert safety.is_read_only is False
    assert safety.is_destructive is False
    assert safety.is_concurrency_safe is False


def test_build_tool_read_only_flags() -> None:
    tool = build_tool(
        name="peek",
        description="peek",
        func=lambda x="": "ok",
        args_schema=_EmptyIn,
        is_read_only=True,
        is_concurrency_safe=True,
        activity_description=lambda d: f"Peeking {d.get('x', '')}",
    )
    safety = get_tool_safety(tool)
    assert safety.is_read_only is True
    assert safety.is_concurrency_safe is True
    from choreoai_cli.tools.base import activity_description as act

    assert act(tool, {"x": "a"}) == "Peeking a"


@pytest.mark.asyncio
async def test_query_engine_submit_events(
    tmp_project: Path, fake_final_only: FakeChatModel
) -> None:
    engine = QueryEngine.create(
        model=fake_final_only, cwd=tmp_project, auto=True, step_budget=5
    )
    events = []
    async for ev in engine.submit("hi"):
        events.append(ev)

    assert isinstance(events[0], TurnStarted)
    assert events[0].prompt == "hi"
    assert isinstance(events[-1], TurnFinished)
    assert events[-1].outcome == TurnOutcome.COMPLETED
    assert events[-1].output == "final answer"
    assert engine.last_outcome == TurnOutcome.COMPLETED


@pytest.mark.asyncio
async def test_query_engine_tool_flow(
    tmp_project: Path, fake_with_list_dir: FakeChatModel
) -> None:
    engine = QueryEngine.create(
        model=fake_with_list_dir, cwd=tmp_project, auto=True, max_steps=5
    )
    kinds = []
    async for ev in engine.submit("list"):
        kinds.append(ev.kind)
    assert "started" in kinds
    assert "tool_call" in kinds
    assert "finished" in kinds
