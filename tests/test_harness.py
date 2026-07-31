"""Offline harness tests: agent + tools + budget wiring (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

# Import choreo.core before choreo.reliability to avoid a package circular import.
from choreo.core import BudgetMiddleware, OnionMiddlewareStack  # noqa: F401
from choreo.reliability import BudgetDimensions, BudgetExhausted, InMemoryBudget

from choreo_cli.harness import CodingHarness
from fakes import FakeChatModel


@pytest.mark.asyncio
async def test_harness_final_only(tmp_project: Path, fake_final_only: FakeChatModel) -> None:
    harness = CodingHarness.create(
        model=fake_final_only,
        cwd=tmp_project,
        auto=True,
        step_budget=5,
    )
    assert isinstance(harness.agent, Runnable)

    result = await harness.arun("say hi")
    assert result.output == "final answer"
    assert result.run_id

    types = [e.type for e in result.events]
    assert "run_started" in types
    assert "run_finished" in types
    assert "step_finished" in types  # agent and/or harness trace

    snap = result.budget_snapshot
    assert snap.consumed.get("steps", 0) >= 1
    assert "steps" in harness.budget_summary()
    assert "run_" in harness.trace_summary() or "llm_" in harness.trace_summary()


@pytest.mark.asyncio
async def test_harness_tool_call_flow(
    tmp_project: Path, fake_with_list_dir: FakeChatModel
) -> None:
    harness = CodingHarness.create(
        model=fake_with_list_dir,
        cwd=tmp_project,
        auto=True,
        max_steps=5,
        step_budget=10,
    )
    result = await harness.arun("what files are here?")
    assert result.output == "I listed the directory."
    assert fake_with_list_dir.call_count == 2

    tool_events = [e for e in result.events if e.type == "tool_called"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_name == "list_dir"
    assert tool_events[0].success is True

    summary = harness.trace_summary()
    assert "tool_called" in summary
    assert "list_dir" in summary


@pytest.mark.asyncio
async def test_harness_read_file_tool_flow(tmp_project: Path) -> None:
    model = FakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"path": "hello.txt"},
                        "id": "call_r1",
                    }
                ],
            ),
            AIMessage(content="The file says hello world."),
        ]
    )
    harness = CodingHarness.create(model=model, cwd=tmp_project, auto=True)
    result = await harness.arun("read hello.txt")
    assert "hello world" in str(result.output)
    tool_events = [e for e in result.events if e.type == "tool_called"]
    assert tool_events[0].tool_name == "read_file"
    assert tool_events[0].success is True


@pytest.mark.asyncio
async def test_budget_exhaustion_blocks_second_turn(tmp_project: Path) -> None:
    """Budget middleware consumes 1 step per harness invocation; cap=1 blocks 2nd."""
    model = FakeChatModel(responses=[AIMessage(content="ok")])
    # step_budget=1: first arun consumes the only step; second should fail.
    # Note: each arun creates a fresh RunContext ledger seeded from caps, so
    # exhaustion is per-context. Re-use the same context by calling stack
    # twice via a single harness budget without fresh context would differ.
    # Here we verify middleware raises when the *shared* budget object is
    # already exhausted without context.
    budget = InMemoryBudget(caps={BudgetDimensions.STEPS.value: 1})

    async def node(value: object) -> object:
        return value

    stack = OnionMiddlewareStack(
        [BudgetMiddleware(budget, amounts={BudgetDimensions.STEPS.value: 1.0})],
        node=node,
    )
    assert await stack.ainvoke("a") == "a"
    with pytest.raises(BudgetExhausted):
        await stack.ainvoke("b")


def test_sync_run(tmp_project: Path, fake_final_only: FakeChatModel) -> None:
    harness = CodingHarness.create(model=fake_final_only, cwd=tmp_project, auto=True)
    result = harness.run("ping")
    assert result.output == "final answer"
