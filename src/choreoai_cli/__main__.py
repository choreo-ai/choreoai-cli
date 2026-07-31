"""Console entry point for choreoai-cli."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    # Before any Rich Console / banner: force UTF-8 and pick glyph mode.
    from choreoai_cli.ui.theme import init_output

    init_output()

    parser = argparse.ArgumentParser(
        prog="choreoai-cli",
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
    parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "Force demo mode: scripted mock model (tool cards + Markdown answer) "
            "without calling a live API. Auto-enabled when ANTHROPIC_API_KEY is unset."
        ),
    )
    args = parser.parse_args(argv)

    from choreoai_cli.app import config_from_args, run_app

    config = config_from_args(
        cwd=args.cwd,
        auto=args.auto,
        max_steps=args.max_steps,
        step_budget=args.step_budget,
        command=args.command,
        demo=args.demo,
    )
    return run_app(config)


if __name__ == "__main__":
    sys.exit(main())
