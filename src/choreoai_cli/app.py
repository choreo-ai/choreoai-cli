"""Application setup and orchestration.

Startup phases (adapted from Claude Code's architecture overview):
  1. Parse config / flags
  2. Init output (UTF-8 + glyphs)
  3. Build QueryEngine (tools, permissions, budget)
  4. Run one-shot (-c) or interactive REPL
"""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console

from choreoai_cli.config import CliConfig
from choreoai_cli.engine.query_engine import QueryEngine
from choreoai_cli.permissions.context import PermissionContext
from choreoai_cli.repl import (
    build_demo_harness,
    build_live_harness,
    print_result,
    run_repl,
)
from choreoai_cli.ui.theme import init_output, make_console


def has_anthropic_api_key() -> bool:
    """True when ``ANTHROPIC_API_KEY`` is set to a non-empty value."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def should_use_demo(config: CliConfig) -> bool:
    """Decide demo vs live model.

    Demo when ``--demo`` is set, or when no API key is present (so the shell
    still starts and shows the full UI). Live only with a real key and no
    ``--demo``. Offline tests inject their own model and never call this.
    """
    if config.demo:
        return True
    return not has_anthropic_api_key()


def build_engine(config: CliConfig) -> QueryEngine:
    """Construct the per-session QueryEngine from CLI config."""
    kwargs = dict(
        cwd=config.cwd,
        auto=config.auto,
        max_steps=config.max_steps,
        step_budget=config.step_budget,
    )
    if should_use_demo(config):
        return build_demo_harness(**kwargs)
    return build_live_harness(**kwargs)


def run_oneshot(
    engine: QueryEngine,
    command: str,
    *,
    console: Console,
) -> int:
    """Execute a single instruction non-interactively, then exit."""
    try:
        result = engine.run(command)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        return 1
    print_result(console, engine, result)
    return 0


def run_app(config: CliConfig, *, console: Console | None = None) -> int:
    """Top-level orchestration: build engine, run one-shot or REPL."""
    init_output()
    console = console or make_console()

    demo = should_use_demo(config)
    try:
        engine = build_engine(config)
    except Exception as exc:
        console.print(f"[red]Failed to start harness: {exc}[/red]")
        if demo:
            console.print(
                "[dim]Tip: demo mode failed to start; ensure choreoai is installed.[/dim]"
            )
        else:
            console.print(
                "[dim]Tip: set ANTHROPIC_API_KEY and ensure choreoai is installed.[/dim]"
            )
        return 1

    if config.command is not None:
        return run_oneshot(engine, config.command, console=console)

    return run_repl(engine, console=console, demo=demo)


def config_from_args(
    *,
    cwd: Path | None = None,
    auto: bool = False,
    max_steps: int = 10,
    step_budget: float = 20.0,
    command: str | None = None,
    demo: bool = False,
) -> CliConfig:
    """Build CliConfig from parsed argparse values."""
    root = cwd.resolve() if cwd is not None else Path.cwd()
    return CliConfig(
        cwd=root,
        auto=auto,
        max_steps=max_steps,
        step_budget=step_budget,
        command=command,
        demo=demo,
    )


def permission_context_for_config(config: CliConfig) -> PermissionContext:
    """Map CLI config to a PermissionContext."""
    return PermissionContext.from_auto(config.auto)
