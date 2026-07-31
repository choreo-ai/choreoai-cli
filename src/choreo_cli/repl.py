"""Interactive REPL for the coding-agent harness."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from choreo_cli.harness import CodingHarness, RunResult

HELP_TEXT = """\
Commands:
  /help   Show this help
  /reset  Clear session note (new budget/trace per turn already)
  /exit   Quit the REPL

Anything else is sent to the coding agent as an instruction.
"""


def _print_tool_events(console: Console, result: RunResult) -> None:
    tools = [e for e in result.events if getattr(e, "type", None) == "tool_called"]
    if not tools:
        return
    table = Table(title="Tool calls", show_header=True, header_style="bold")
    table.add_column("tool")
    table.add_column("ok")
    table.add_column("ms")
    for e in tools:
        ok = "yes" if getattr(e, "success", False) else "no"
        ms = getattr(e, "duration_ms", None)
        ms_s = f"{ms:.0f}" if isinstance(ms, (int, float)) else "-"
        table.add_row(str(getattr(e, "tool_name", "?")), ok, ms_s)
    console.print(table)


def _print_result(console: Console, harness: CodingHarness, result: RunResult) -> None:
    _print_tool_events(console, result)

    text = result.output if result.output is not None else "(no output)"
    if not isinstance(text, str):
        text = str(text)
    console.print(Panel(Markdown(text) if text.strip() else text, title="Answer", border_style="cyan"))

    snap = result.budget_snapshot
    budget_line = "budget: "
    if snap is not None:
        parts = []
        for dim, cap in snap.caps.items():
            used = snap.consumed.get(dim, 0.0)
            parts.append(f"{dim} {used:g}/{cap:g}")
        budget_line += ", ".join(parts) if parts else "n/a"
    else:
        budget_line += harness.budget_summary()

    console.print(f"[dim]{budget_line}[/dim]")
    console.print(f"[dim]trace: {harness.trace_summary()}[/dim]")


def run_repl(
    harness: CodingHarness,
    *,
    console: Console | None = None,
    input_fn: Any = input,
) -> int:
    """Run the interactive loop until /exit or EOF. Returns process exit code."""
    console = console or Console()
    cwd = harness.cwd
    console.print(
        Panel(
            f"choreo-cli coding agent\ncwd: {cwd}\nType /help for commands, /exit to quit.",
            title="choreo-cli",
            border_style="green",
        )
    )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[yellow]Note: ANTHROPIC_API_KEY is not set. "
            "Live model calls will fail; offline/tests inject a fake model.[/yellow]"
        )

    while True:
        try:
            line = input_fn("choreo> ")
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
            console.print(HELP_TEXT)
            continue
        if text == "/reset":
            harness.reset_trace()
            console.print("[dim]Trace cleared. Each turn already uses a fresh budget ledger.[/dim]")
            continue
        if text.startswith("/"):
            console.print(f"[yellow]Unknown command: {text}. Try /help.[/yellow]")
            continue

        try:
            result = harness.run(text)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")
            continue

        _print_result(console, harness, result)

    console.print("[dim]bye[/dim]")
    return 0


def build_live_harness(
    *,
    cwd: Path | None = None,
    auto: bool = False,
    max_steps: int = 10,
    step_budget: float = 20.0,
) -> CodingHarness:
    """Build a harness with the default Claude model (needs ANTHROPIC_API_KEY)."""
    from choreo.models import get_default_model

    model = get_default_model()
    return CodingHarness.create(
        model=model,
        cwd=cwd,
        auto=auto,
        max_steps=max_steps,
        step_budget=step_budget,
    )
