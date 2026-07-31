"""Interactive REPL for the coding-agent harness."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from choreo.core.events import Event, Subscriber

from choreo_cli.harness import CodingHarness, RunResult

HELP_TEXT = """\
Commands:
  /help   Show this help
  /reset  Clear session budget ledger, shell approvals, and trace
  /exit   Quit the REPL

Anything else is sent to the coding agent as an instruction.

Shell approval (when not --auto):
  y / yes           allow this command once
  n / no            deny this command once
  always / a        allow all shell commands for this session
  deny <pattern>    reject commands containing <pattern> for this session
"""


class LiveEventSubscriber(Subscriber):
    """Print tool-call (and related) events to the console as they arrive."""

    name = "live_repl"

    def __init__(self, console: Console, *, name: str = "live_repl") -> None:
        self.name = name
        self.console = console

    async def on_event(self, event: Event) -> None:
        etype = getattr(event, "type", None)
        if etype == "tool_called":
            tool_name = getattr(event, "tool_name", "?")
            ok = getattr(event, "success", False)
            ms = getattr(event, "duration_ms", None)
            ms_s = f" ({ms:.0f}ms)" if isinstance(ms, (int, float)) else ""
            err = getattr(event, "error", None)
            status = "ok" if ok else "fail"
            line = f"[bold cyan]tool[/bold cyan] {tool_name} [{status}]{ms_s}"
            if err:
                line += f" — {err}"
            self.console.print(line)
        elif etype == "llm_called":
            ok = getattr(event, "success", True)
            if not ok:
                err = getattr(event, "error", None) or "llm error"
                self.console.print(f"[yellow]llm[/yellow] fail — {err}")
        elif etype == "run_started":
            self.console.print("[dim]run started…[/dim]")
        elif etype == "run_finished":
            status = getattr(event, "status", "?")
            self.console.print(f"[dim]run finished ({status})[/dim]")


def _print_result(console: Console, harness: CodingHarness, result: RunResult) -> None:
    text = result.output if result.output is not None else "(no output)"
    if not isinstance(text, str):
        text = str(text)
    console.print(
        Panel(
            Markdown(text) if text.strip() else text,
            title="Answer",
            border_style="cyan",
        )
    )

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
    live_stream: bool = True,
) -> int:
    """Run the interactive loop until /exit or EOF. Returns process exit code."""
    console = console or Console()
    cwd = harness.cwd
    console.print(
        Panel(
            f"choreoai-cli coding agent\ncwd: {cwd}\n"
            "Type /help for commands, /exit to quit.",
            title="choreoai-cli",
            border_style="green",
        )
    )

    if live_stream:
        harness.add_subscriber(LiveEventSubscriber(console))

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
            harness.reset_session()
            console.print(
                "[dim]Session reset: budget ledger, shell approvals, and trace cleared.[/dim]"
            )
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
