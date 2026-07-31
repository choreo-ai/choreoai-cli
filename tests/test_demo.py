"""Tests for demo / mock mode (no API key, offline)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from choreoai_cli.app import (
    config_from_args,
    has_anthropic_api_key,
    should_use_demo,
)
from choreoai_cli.config import CliConfig
from choreoai_cli.engine.mock_model import (
    DemoChatModel,
    choose_scenario,
    make_demo_model,
)
from choreoai_cli.repl import (
    build_demo_harness,
    run_repl,
    sync_demo_usage,
)
from choreoai_cli.ui.toolcards import LiveEventSubscriber


def test_choose_scenario_is_stable() -> None:
    a = choose_scenario("refactor the auth module")
    b = choose_scenario("refactor the auth module")
    assert a == b
    assert a in ("explore", "shell", "deep")


def test_choose_scenario_varies() -> None:
    names = {choose_scenario(f"prompt-{i}-unique-enough") for i in range(40)}
    assert len(names) >= 2


def test_demo_model_tool_loop(tmp_project: Path) -> None:
    model = make_demo_model(cwd=tmp_project, delay_s=0)
    harness = build_demo_harness(cwd=tmp_project, auto=True, delay_s=0)
    # build_demo_harness makes its own model; use that path end-to-end.
    result = harness.run("refactor the auth module")
    assert result.output
    assert "Demo" in str(result.output) or "demo" in str(result.output).lower()
    tool_events = [e for e in result.events if getattr(e, "type", None) == "tool_called"]
    assert len(tool_events) >= 1
    names = {e.tool_name for e in tool_events}
    assert names & {"read_file", "list_dir", "run_shell"}


def test_demo_model_direct_generate(tmp_project: Path) -> None:
    from langchain_core.messages import HumanMessage

    model = DemoChatModel(cwd=tmp_project, delay_s=0)
    r1 = model.invoke([HumanMessage(content="list project files please")])
    assert r1.tool_calls
    assert model.turn_input_tokens > 0
    inn, out = model.drain_usage()
    assert inn > 0 and out > 0
    assert model.turn_input_tokens == 0


def test_should_use_demo_flag_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = CliConfig(cwd=Path("."), demo=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert should_use_demo(cfg) is True

    cfg2 = CliConfig(cwd=Path("."), demo=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert should_use_demo(cfg2) is True
    assert has_anthropic_api_key() is False

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-live")
    assert should_use_demo(cfg2) is False
    assert has_anthropic_api_key() is True


def test_config_from_args_demo() -> None:
    cfg = config_from_args(cwd=Path("."), demo=True)
    assert cfg.demo is True


def test_run_repl_demo_end_to_end(tmp_project: Path) -> None:
    engine = build_demo_harness(cwd=tmp_project, auto=True, delay_s=0)
    lines = iter(["explore this project", "/exit"])
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=100, quiet=False)
    code = run_repl(
        engine,
        console=console,
        input_fn=lambda _p: next(lines),
        live_stream=True,
        use_spinner=False,
        history_file=False,
        demo=True,
    )
    assert code == 0
    out = buf.getvalue()
    assert "Demo mode" in out
    assert "Answer" in out
    assert "bye" in out.lower()
    # At least one tool card name should appear from the live subscriber.
    assert "read_file" in out or "list_dir" in out or "run_shell" in out


def test_sync_demo_usage(tmp_project: Path) -> None:
    engine = build_demo_harness(cwd=tmp_project, auto=True, delay_s=0)
    console = Console(file=StringIO(), force_terminal=False, width=80)
    live = LiveEventSubscriber(console)
    engine.run("hi")
    sync_demo_usage(engine.harness, live)
    assert live.total_input_tokens > 0
    assert live.total_output_tokens > 0
