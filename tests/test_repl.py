"""Offline tests for the interactive REPL wiring (no TTY, no network)."""

from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from rich.console import Console

from choreoai.core.events import LLMCalled, RunFinished, RunStarted, ToolCalled

from choreo_cli.harness import CodingHarness
from choreo_cli.repl import (
    LiveEventSubscriber,
    _looks_like_code,
    _render_answer_body,
    make_prompt_fn,
    print_result,
    run_repl,
)
from fakes import FakeChatModel


def _console() -> Console:
    """Non-TTY console suitable for offline capture."""
    return Console(file=StringIO(), force_terminal=False, width=80)


@pytest.mark.asyncio
async def test_live_subscriber_renders_tool_and_llm_events() -> None:
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80, soft_wrap=True)
    live = LiveEventSubscriber(console)

    await live.on_event(
        ToolCalled(
            run_id="r1",
            seq=1,
            ts=datetime.now(timezone.utc),
            tool_name="list_dir",
            success=True,
            duration_ms=12.5,
        )
    )
    await live.on_event(
        LLMCalled(
            run_id="r1",
            seq=2,
            ts=datetime.now(timezone.utc),
            model="fake",
            input_tokens=10,
            output_tokens=5,
            duration_ms=100.0,
            success=True,
        )
    )
    await live.on_event(
        RunStarted(run_id="r1", seq=0, ts=datetime.now(timezone.utc))
    )
    await live.on_event(
        RunFinished(run_id="r1", seq=3, ts=datetime.now(timezone.utc), status="ok")
    )

    out = buf.getvalue()
    assert "list_dir" in out
    assert "tool" in out.lower() or "#" in out
    assert live.tool_count == 1
    assert live.llm_count == 1
    assert live.total_input_tokens == 10
    assert live.total_output_tokens == 5


def test_make_prompt_fn_force_plain_uses_builtin_input() -> None:
    fn = make_prompt_fn(force_plain=True)
    assert fn is input


def test_looks_like_code_and_render() -> None:
    code = "def foo():\n    return 1\n"
    assert _looks_like_code(code) is True
    assert _looks_like_code("Hello, here is a summary.") is False
    body = _render_answer_body(code)
    # Syntax object for code-ish text
    assert body.__class__.__name__ in ("Syntax", "Markdown", "Text")


def test_print_result_includes_budget(tmp_project: Path, fake_final_only: FakeChatModel) -> None:
    harness = CodingHarness.create(
        model=fake_final_only, cwd=tmp_project, auto=True, step_budget=5
    )
    result = harness.run("hi")
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80)
    live = LiveEventSubscriber(console)
    live.tool_count = 1
    live.llm_count = 1
    live.total_input_tokens = 3
    live.total_output_tokens = 7
    print_result(console, harness, result, live=live)
    out = buf.getvalue()
    assert "Answer" in out or "final answer" in out
    assert "budget" in out.lower() or "steps" in out


def test_run_repl_help_reset_exit(
    tmp_project: Path, fake_final_only: FakeChatModel
) -> None:
    """Drive the REPL with a scripted input_fn: /help, /reset, agent turn, /exit."""
    harness = CodingHarness.create(
        model=fake_final_only, cwd=tmp_project, auto=True, step_budget=10
    )
    lines = iter(["/help", "/reset", "say hi", "/exit"])
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80, quiet=False)

    code = run_repl(
        harness,
        console=console,
        input_fn=lambda _p: next(lines),
        live_stream=True,
        use_spinner=False,
        history_file=False,
    )
    assert code == 0
    out = buf.getvalue()
    assert "/help" in out or "Commands" in out or "Show this help" in out
    assert "Session reset" in out or "reset" in out.lower()
    assert "final answer" in out
    assert "bye" in out.lower()


def test_run_repl_eof_exits_cleanly(
    tmp_project: Path, fake_final_only: FakeChatModel
) -> None:
    harness = CodingHarness.create(
        model=fake_final_only, cwd=tmp_project, auto=True
    )

    def boom(_p: str) -> str:
        raise EOFError

    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80)
    code = run_repl(
        harness,
        console=console,
        input_fn=boom,
        live_stream=False,
        use_spinner=False,
        history_file=False,
    )
    assert code == 0
    assert "bye" in buf.getvalue().lower()


def test_run_repl_unknown_slash_command(
    tmp_project: Path, fake_final_only: FakeChatModel
) -> None:
    harness = CodingHarness.create(
        model=fake_final_only, cwd=tmp_project, auto=True
    )
    lines = iter(["/nope", "/exit"])
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80)
    code = run_repl(
        harness,
        console=console,
        input_fn=lambda _p: next(lines),
        live_stream=False,
        use_spinner=False,
        history_file=False,
    )
    assert code == 0
    assert "Unknown command" in buf.getvalue()


@pytest.mark.asyncio
async def test_live_stream_during_harness_run(
    tmp_project: Path, fake_with_list_dir: FakeChatModel
) -> None:
    """End-to-end: LiveEventSubscriber sees tool events from a real harness run."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80)
    live = LiveEventSubscriber(console)
    harness = CodingHarness.create(
        model=fake_with_list_dir, cwd=tmp_project, auto=True, max_steps=5
    )
    harness.add_subscriber(live)
    result = await harness.arun("list files")
    assert result.output == "I listed the directory."
    assert live.tool_count == 1
    out = buf.getvalue()
    assert "list_dir" in out
