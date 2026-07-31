"""Console entry point for choreo-cli."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="choreo-cli",
        description="Interactive coding-agent harness built on choreoai.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Working directory for tools (default: current directory).",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Skip confirmation prompts for run_shell (use with care).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=10,
        help="Max LLM tool-loop steps per turn (default: 10).",
    )
    parser.add_argument(
        "--step-budget",
        type=float,
        default=20.0,
        help="Harness step budget cap per turn (default: 20).",
    )
    parser.add_argument(
        "-c",
        "--command",
        type=str,
        default=None,
        help="Run a single instruction non-interactively, then exit.",
    )
    args = parser.parse_args(argv)

    from rich.console import Console

    from choreo_cli.repl import build_live_harness, run_repl, _print_result

    console = Console()
    cwd = args.cwd.resolve() if args.cwd else Path.cwd()

    try:
        harness = build_live_harness(
            cwd=cwd,
            auto=args.auto,
            max_steps=args.max_steps,
            step_budget=args.step_budget,
        )
    except Exception as exc:
        console.print(f"[red]Failed to start harness: {exc}[/red]")
        console.print(
            "[dim]Tip: set ANTHROPIC_API_KEY and ensure choreoai is installed.[/dim]"
        )
        return 1

    if args.command is not None:
        try:
            result = harness.run(args.command)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")
            return 1
        _print_result(console, harness, result)
        return 0

    return run_repl(harness, console=console)


if __name__ == "__main__":
    sys.exit(main())
