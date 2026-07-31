"""Offline harness tests: agent + tools + budget wiring (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from choreoai.core import BudgetMiddleware, OnionMiddlewareStack
from choreoai.core.events import Event, Subscriber
from choreoai.reliability import BudgetDimensions, BudgetExhausted, InMemoryBudget

from choreoai_cli.harness import CodingHarness
from choreoai_cli.repl import LiveEventSubscriber
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
async def test_session_budget_accumulates_across_turns(tmp_project: Path) -> None:
    """One shared RunContext ledger: step_budget=2 allows two turns, blocks third."""
    model = FakeChatModel(responses=[AIMessage(content="ok")])
    # Reuse the same model instance; FakeChatModel reuses last response when exhausted.
    harness = CodingHarness.create(
        model=model,
        cwd=tmp_project,
        auto=True,
        step_budget=2,
    )

    r1 = await harness.arun("turn 1")
    assert r1.output == "ok"
    assert r1.budget_snapshot.consumed.get("steps", 0) == 1

    r2 = await harness.arun("turn 2")
    assert r2.output == "ok"
    assert r2.budget_snapshot.consumed.get("steps", 0) == 2
    # Same session run_id across turns.
    assert r1.run_id == r2.run_id

    with pytest.raises(BudgetExhausted):
        await harness.arun("turn 3")

    # /reset clears the session ledger.
    harness.reset_session()
    r4 = await harness.arun("after reset")
    assert r4.output == "ok"
    assert r4.budget_snapshot.consumed.get("steps", 0) == 1
    assert r4.run_id != r1.run_id


@pytest.mark.asyncio
async def test_live_event_subscriber_receives_tool_events(
    tmp_project: Path, fake_with_list_dir: FakeChatModel
) -> None:
    """Subscriber sees tool_called events as the harness run emits them."""

    class CollectingLive(Subscriber):
        name = "collect_live"

        def __init__(self) -> None:
            self.seen: list[Event] = []

        async def on_event(self, event: Event) -> None:
            self.seen.append(event)

    live = CollectingLive()
    harness = CodingHarness.create(
        model=fake_with_list_dir,
        cwd=tmp_project,
        auto=True,
        max_steps=5,
    )
    harness.add_subscriber(live)

    result = await harness.arun("list files")
    assert result.output == "I listed the directory."

    live_tools = [e for e in live.seen if e.type == "tool_called"]
    assert len(live_tools) == 1
    assert live_tools[0].tool_name == "list_dir"

    # LiveEventSubscriber itself is constructible (used by REPL).
    from rich.console import Console

    sub = LiveEventSubscriber(Console(quiet=True))
    assert sub.name == "live_repl"


@pytest.mark.asyncio
async def test_budget_exhaustion_blocks_second_turn(tmp_project: Path) -> None:
    """Budget middleware consumes 1 step per harness invocation; cap=1 blocks 2nd."""
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
