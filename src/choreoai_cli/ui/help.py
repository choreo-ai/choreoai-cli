"""Slash-command help rendering."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from choreoai_cli.ui.theme import SAND, TAUPE, TERRACOTTA, glyphs, gutter_pad

SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help", "Show available commands"),
    ("/reset", "Clear session budget, shell approvals, and trace"),
    ("/exit", "Quit the REPL"),
]

# Back-compat: tests and older docs may reference HELP_TEXT.
HELP_TEXT = """\
Commands:
  /help   Show this help
  /reset  Clear session budget ledger, shell approvals, and trace
  /exit   Quit the REPL

Anything else is sent to the coding agent as an instruction.

Input:
  Enter           submit (single-line mode)
  Esc then Enter  newline (multiline)
  Ctrl+C / Ctrl+D quit
  Up/Down         history (prompt_toolkit)

Shell approval (when not --auto):
  y / yes           allow this command once
  n / no            deny this command once
  always / a        allow all shell commands for this session
  deny <pattern>    reject commands containing <pattern> for this session
"""


def print_help(console: Console) -> None:
    """Render slash-command help as a clean table."""
    table = Table(
        show_header=True,
        header_style=f"bold {TERRACOTTA}",
        border_style=TAUPE,
        box=None,
        padding=(0, 2),
        expand=False,
        pad_edge=False,
    )
    table.add_column("Command", style=f"bold {SAND}")
    table.add_column("Description", style=TAUPE)
    for cmd, desc in SLASH_COMMANDS:
        table.add_row(cmd, desc)

    console.print()
    console.print(gutter_pad(Text("Commands", style=f"bold {SAND}")))
    console.print(gutter_pad(table))
    console.print()

    tips = Text()
    tips.append("Input", style=f"bold {SAND}")
    tips.append("\n", style="")
    tips.append("  Enter", style=SAND)
    tips.append("  send", style=TAUPE)
    tips.append(f"  {glyphs().middot}  ", style=f"dim {TAUPE}")
    tips.append("Esc+Enter / Shift+Enter", style=SAND)
    tips.append("  newline\n", style=TAUPE)
    tips.append("  Up/Down", style=SAND)
    tips.append("  history", style=TAUPE)
    tips.append(f"  {glyphs().middot}  ", style=f"dim {TAUPE}")
    tips.append("Ctrl+C", style=SAND)
    tips.append("  quit\n", style=TAUPE)
    tips.append("\nShell approval", style=f"bold {SAND}")
    tips.append(" (when not --auto)\n", style=TAUPE)
    tips.append(
        f"  y / yes {glyphs().middot} n / no {glyphs().middot} "
        f"always / a {glyphs().middot} deny <pattern>\n",
        style=TAUPE,
    )
    tips.append(
        "\nAnything else is sent to the coding agent as an instruction.",
        style=TAUPE,
    )
    console.print(gutter_pad(tips))
    console.print()
