"""Thin REPL loop wiring ui/ + engine/ pieces.

Inline Claude-Code / Grok-style terminal UI: **rich** for streamed rendering
and **prompt_toolkit** for framed multiline input. Full-screen / alt-screen
TUIs are intentionally avoided so agent output can stream into normal
terminal scrollback.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from choreoai_cli.engine.query_engine import CodingHarness, QueryEngine
from choreoai_cli.ui.footer import print_result
from choreoai_cli.ui.header import (
    model_label,
    print_api_key_note,
    print_banner,
    print_demo_mode_note,
)
from choreoai_cli.ui.help import HELP_TEXT, print_help
from choreoai_cli.ui.prompt import history_path, make_live_toolbar, make_prompt_fn
from choreoai_cli.ui.theme import TAUPE, TERRACOTTA, glyphs, gutter_pad, make_console
from choreoai_cli.ui.toolcards import (
    LiveEventSubscriber,
    ToolArgTracker,
    instrument_tools_for_ui,
)

# Re-exports for tests / external callers that import from repl.
from choreoai_cli.ui.answer import looks_like_code as _looks_like_code
from choreoai_cli.ui.answer import render_answer_body as _render_answer_body

__all__ = [
    "HELP_TEXT",
    "LiveEventSubscriber",
    "ToolArgTracker",
    "_looks_like_code",
    "_print_result",
    "_render_answer_body",
    "build_demo_harness",
    "build_live_harness",
    "make_prompt_fn",
    "print_result",
    "run_repl",
    "sync_demo_usage",
]

_print_result = print_result


def _instrument_harness(harness: CodingHarness) -> ToolArgTracker:
    """Install arg tracker so tool cards show key arguments."""
    arg_tracker = getattr(harness, "tool_arg_tracker", None)
    if arg_tracker is None:
        arg_tracker = ToolArgTracker()
        harness.tool_arg_tracker = arg_tracker  # type: ignore[attr-defined]
        try:
            tools = list(harness.agent.tools)
            instrumented = instrument_tools_for_ui(tools, arg_tracker)
            harness.agent.tools = instrumented
            harness.agent._tool_map = {t.name: t for t in instrumented}  # noqa: SLF001
        except Exception:
            pass
    return arg_tracker


def _is_demo_model(harness: Any) -> bool:
    agent = getattr(harness, "agent", None)
    model = getattr(agent, "model", None) if agent is not None else None
    return bool(getattr(model, "is_demo", False))


def sync_demo_usage(harness: Any, live: LiveEventSubscriber | None) -> None:
    """Copy mock token usage into live footer stats (agent events omit tokens)."""
    if live is None:
        return
    agent = getattr(harness, "agent", None)
    model = getattr(agent, "model", None) if agent is not None else None
    if model is None or not getattr(model, "is_demo", False):
        return
    drain = getattr(model, "drain_usage", None)
    if not callable(drain):
        return
    inn, out = drain()
    if inn or out:
        live.total_input_tokens = int(inn)
        live.total_output_tokens = int(out)
        live.stats.total_input_tokens = live.total_input_tokens
        live.stats.total_output_tokens = live.total_output_tokens


def run_repl(
    harness: CodingHarness | QueryEngine,
    *,
    console: Console | None = None,
    input_fn: Any = None,
    live_stream: bool = True,
    use_spinner: bool = True,
    multiline: bool = True,
    history_file: Path | None | bool = None,
    demo: bool | None = None,
) -> int:
    """Run the interactive loop until /exit or EOF. Returns process exit code."""
    # Accept QueryEngine or CodingHarness.
    core: CodingHarness = (
        harness.harness if isinstance(harness, QueryEngine) else harness
    )
    console = console or make_console()
    cwd = core.cwd
    g = glyphs()
    if demo is None:
        demo = _is_demo_model(core)

    arg_tracker = _instrument_harness(core)

    if input_fn is None:
        if history_file is False:
            hist: Path | None = None
        elif history_file is None:
            hist = history_path()
        else:
            hist = history_file
        force_plain = not console.is_terminal
        input_fn = make_prompt_fn(
            history_file=hist,
            multiline=multiline,
            force_plain=force_plain,
            toolbar_fn=make_live_toolbar(core) if not force_plain else None,
            model_name=model_label(core),
            cwd=cwd,
        )

    print_banner(console, core)
    if demo:
        print_demo_mode_note(console)
    else:
        print_api_key_note(console)

    live: LiveEventSubscriber | None = None
    if live_stream:
        live = LiveEventSubscriber(console, arg_tracker=arg_tracker)
        core.add_subscriber(live)

    spinner_ok = use_spinner and console.is_terminal and not console.quiet

    while True:
        try:
            line = input_fn(f"  {g.prompt} ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if line is None:
            break
        text = str(line).strip()
        if not text:
            continue

        if text in ("/exit", "/quit", "exit", "quit"):
            break
        if text == "/help":
            print_help(console)
            continue
        if text == "/reset":
            if isinstance(harness, QueryEngine):
                harness.reset_session()
            else:
                core.reset_session()
            if live is not None:
                live.reset_turn_stats()
            if arg_tracker is not None:
                arg_tracker.clear()
            console.print()
            console.print(
                gutter_pad(
                    Text(
                        "Session reset: budget ledger, shell approvals, and "
                        "trace cleared.",
                        style=f"dim {TAUPE}",
                    )
                )
            )
            console.print()
            continue
        if text.startswith("/"):
            console.print()
            console.print(
                gutter_pad(
                    Text(f"Unknown command: {text}. Try /help.", style="yellow")
                )
            )
            console.print()
            continue

        if live is not None:
            live.reset_turn_stats()

        t0 = time.perf_counter()
        try:
            if spinner_ok:
                with console.status(
                    f"[{TERRACOTTA}]orchestrating{g.ellipsis}[/{TERRACOTTA}]",
                    spinner="dots",
                ) as status:
                    if live is not None:
                        live.bind_status(status)
                    try:
                        result = core.run(text)
                    finally:
                        if live is not None:
                            live.bind_status(None)
            else:
                result = core.run(text)
        except KeyboardInterrupt:
            console.print()
            console.print(
                gutter_pad(Text("Turn cancelled.", style=f"dim {TAUPE}"))
            )
            console.print()
            continue
        except Exception as exc:
            console.print()
            console.print(gutter_pad(Text(f"Error: {exc}", style="red")))
            console.print()
            continue

        elapsed = time.perf_counter() - t0
        sync_demo_usage(core, live)
        print_result(console, core, result, live=live, elapsed_s=elapsed)

    console.print()
    console.print(gutter_pad(Text("bye", style=f"dim {TAUPE}")))
    return 0


def _demo_shell_confirm(command: str, *, policy: Any) -> bool:
    """Approve shell in non-TTY pipes so demos stay smooth; else real policy."""
    try:
        if not sys.stdin.isatty():
            return True
    except Exception:
        return True
    return bool(policy(command))


def build_demo_harness(
    *,
    cwd: Path | None = None,
    auto: bool = False,
    max_steps: int = 10,
    step_budget: float = 20.0,
    delay_s: float = 0.12,
) -> QueryEngine:
    """Build a QueryEngine with the scripted demo mock model (no API key)."""
    from choreoai_cli.engine.mock_model import make_demo_model
    from choreoai_cli.permissions.approval import ShellApprovalPolicy
    from choreoai_cli.permissions.context import PermissionContext

    root = (cwd or Path.cwd()).resolve()
    model = make_demo_model(cwd=root, delay_s=delay_s)
    perm = PermissionContext.from_auto(auto)

    confirm = None
    if not auto:
        # Keep interactive shell approval; auto-allow when stdin is piped.
        policy = ShellApprovalPolicy(context=perm)
        confirm = lambda cmd, _p=policy: _demo_shell_confirm(cmd, policy=_p)

    engine = QueryEngine.create(
        model=model,
        cwd=root,
        auto=auto,
        confirm=confirm,
        max_steps=max_steps,
        step_budget=step_budget,
        permission_context=perm,
    )
    _instrument_harness(engine.harness)
    return engine


def build_live_harness(
    *,
    cwd: Path | None = None,
    auto: bool = False,
    max_steps: int = 10,
    step_budget: float = 20.0,
) -> QueryEngine:
    """Build a QueryEngine with the default Claude model (needs ANTHROPIC_API_KEY)."""
    from choreoai.models import get_default_model
    from choreoai_cli.permissions.context import PermissionContext

    model = get_default_model()
    engine = QueryEngine.create(
        model=model,
        cwd=cwd,
        auto=auto,
        max_steps=max_steps,
        step_budget=step_budget,
        permission_context=PermissionContext.from_auto(auto),
    )
    _instrument_harness(engine.harness)
    return engine
