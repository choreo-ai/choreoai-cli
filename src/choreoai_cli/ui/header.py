"""Startup header / banner."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from choreoai_cli.ui.theme import SAND, TAUPE, TERRACOTTA, glyphs


def model_label(harness: Any) -> str:
    model = getattr(harness, "model", None)
    if model is None:
        agent = getattr(harness, "agent", None)
        model = getattr(agent, "model", None) if agent is not None else None
    if model is None:
        return glyphs().emdash
    for attr in ("model", "model_name", "model_id"):
        val = getattr(model, attr, None)
        if isinstance(val, str) and val:
            return val
    return type(model).__name__


def short_cwd(cwd: Path, *, max_len: int = 48) -> str:
    try:
        home = Path.home()
        resolved = cwd.resolve()
        if resolved == home:
            return "~"
        try:
            rel = resolved.relative_to(home)
            s = "~/" + rel.as_posix()
        except ValueError:
            s = str(resolved)
    except OSError:
        s = str(cwd)
    if len(s) > max_len:
        return glyphs().ellipsis + s[-(max_len - 1) :]
    return s


def print_banner(console: Console, harness: Any) -> None:
    """Compact startup header: wordmark, version, cwd, model, hints."""
    from choreoai_cli import __version__

    g = glyphs()
    title = Text()
    title.append(g.bullet, style=f"bold {TERRACOTTA}")
    title.append(" ")
    title.append("ChoreoAI", style=f"bold {SAND}")
    title.append("  ", style="")
    title.append(f"v{__version__}", style=f"dim {TAUPE}")

    cwd = getattr(harness, "cwd", Path("."))
    # Two-column label/value grid so cwd / model values share a start column.
    meta = Table.grid(padding=(0, 2), pad_edge=False, expand=False)
    meta.add_column(style=f"dim {TAUPE}", justify="left", no_wrap=True)
    meta.add_column(style=SAND, justify="left", overflow="fold")
    meta.add_row("cwd", str(cwd))
    meta.add_row("model", model_label(harness))

    hint = Text(
        f"/help for commands {g.middot} Ctrl+C to quit",
        style=f"dim {TAUPE}",
    )

    body = Group(title, Text(""), meta, Text(""), hint)
    console.print(
        Panel(
            body,
            border_style=TERRACOTTA,
            padding=(1, 2),
            expand=True,
        )
    )
    # Blank line after header before the next block / first prompt.
    console.print()


def print_demo_mode_note(console: Console) -> None:
    """One-line note when the session uses the scripted mock model."""
    from choreoai_cli.ui.theme import gutter_pad

    g = glyphs()
    note = Text()
    note.append("Demo mode", style=f"bold {TERRACOTTA}")
    note.append(f" {g.emdash} ", style=f"dim {TAUPE}")
    note.append("mock responses, no API key", style=TAUPE)
    console.print(gutter_pad(note))
    console.print()


def print_api_key_note(console: Console) -> None:
    """Friendly note when the Anthropic key is missing (live path only)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    note = Text()
    note.append("Note", style=f"bold {TERRACOTTA}")
    note.append("  ", style="")
    note.append(
        "ANTHROPIC_API_KEY is not set. Live model calls will fail; "
        "you can still explore /help and the shell. "
        "Offline tests inject a fake model.",
        style=TAUPE,
    )
    console.print(
        Panel(note, border_style=TAUPE, padding=(1, 2), expand=True)
    )
    console.print()
