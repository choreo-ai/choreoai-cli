"""Framed input, bottom toolbar, slash completer (prompt_toolkit)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

from choreoai_cli.ui.header import model_label, short_cwd
from choreoai_cli.ui.help import SLASH_COMMANDS
from choreoai_cli.ui.theme import (
    SAND,
    TAUPE,
    TERRACOTTA,
    TERRACOTTA_DEEP,
    glyphs,
)


def history_path() -> Path:
    """Default path for persistent input history (XDG-ish / home)."""
    base = os.environ.get("CHOREOAI_CLI_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".choreoai-cli"
    return root / "history"


def budget_short(harness: Any) -> str:
    try:
        snap = harness.budget.snapshot(context=harness.session_context)
        parts: list[str] = []
        for dim, cap in snap.caps.items():
            used = snap.consumed.get(dim, 0.0)
            parts.append(f"{dim} {used:g}/{cap:g}")
        sep = f" {glyphs().middot} "
        return sep.join(parts) if parts else "budget n/a"
    except Exception:
        return harness.budget_summary()


def make_prompt_fn(
    *,
    history_file: Path | None = None,
    multiline: bool = True,
    force_plain: bool = False,
    toolbar_fn: Callable[[], Any] | None = None,
    model_name: str = "",
    cwd: Path | None = None,
) -> Callable[[str], str]:
    """Build an input callable: prompt_toolkit when interactive, else ``input``.

    ``force_plain`` and non-TTY stdin force the stdlib ``input`` path so tests
    and pipes never need a real terminal.
    """
    if force_plain or not sys.stdin.isatty() or not sys.stdout.isatty():
        return input

    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.formatted_text import HTML, to_formatted_text
        from prompt_toolkit.history import FileHistory, InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.styles import Style
    except ImportError:
        return input

    history: FileHistory | InMemoryHistory
    if history_file is not None:
        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history = FileHistory(str(history_file))
        except OSError:
            history = InMemoryHistory()
    else:
        history = InMemoryHistory()

    class SlashCompleter(Completer):
        def get_completions(self, document, complete_event):  # type: ignore[no-untyped-def]
            text = document.text_before_cursor.lstrip()
            if not text.startswith("/"):
                return
            if " " in text.strip():
                return
            for cmd, desc in SLASH_COMMANDS:
                if cmd.startswith(text):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=cmd,
                        display_meta=desc,
                    )

    style = Style.from_dict(
        {
            "prompt": f"{TERRACOTTA} bold",
            "continuation": TAUPE,
            "placeholder": TAUPE,
            "bottom-toolbar": f"bg:#1C1917 {TAUPE}",
            "bottom-toolbar.accent": f"bg:#1C1917 {TERRACOTTA}",
            "bottom-toolbar.sand": f"bg:#1C1917 {SAND}",
            "completion-menu": f"bg:#1C1917 {SAND}",
            "completion-menu.completion": f"bg:#1C1917 {SAND}",
            "completion-menu.completion.current": f"bg:{TERRACOTTA_DEEP} #ffffff",
            "completion-menu.meta.completion": f"bg:#1C1917 {TAUPE}",
            "completion-menu.meta.completion.current": f"bg:{TERRACOTTA_DEEP} #ffffff",
        }
    )

    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event: Any) -> None:
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline_esc(event: Any) -> None:
        event.current_buffer.insert_text("\n")

    @kb.add("c-j")
    def _newline_cj(event: Any) -> None:
        event.current_buffer.insert_text("\n")

    try:

        @kb.add("s-enter")
        def _newline_shift(event: Any) -> None:
            event.current_buffer.insert_text("\n")
    except Exception:
        pass

    def _default_toolbar() -> Any:
        g = glyphs()
        model = model_name or "model"
        path = short_cwd(cwd) if cwd is not None else "."
        sep = f'  <style fg="{TAUPE}">{g.middot}</style>  '
        return to_formatted_text(
            HTML(
                f'  <b><style fg="{TERRACOTTA}">{model}</style></b>'
                f"{sep}"
                f'<style fg="{SAND}">{path}</style>'
                f"{sep}"
                f'<style fg="{TAUPE}">↵ send {g.middot} Esc↵ newline '
                f"{g.middot} /help {g.middot} Ctrl+C quit</style>"
            )
        )

    toolbar = toolbar_fn if toolbar_fn is not None else _default_toolbar

    session: PromptSession[str] = PromptSession(
        history=history,
        auto_suggest=AutoSuggestFromHistory(),
        enable_history_search=True,
        multiline=multiline,
        prompt_continuation=lambda width, line_number, is_soft_wrap: "  ",
        style=style,
        completer=SlashCompleter(),
        complete_while_typing=True,
        key_bindings=kb,
        bottom_toolbar=toolbar,
        placeholder=HTML(
            f'<style fg="{TAUPE}">Message the agent{glyphs().ellipsis}  '
            f"(/ for commands)</style>"
        ),
    )

    def _prompt(message: str = "") -> str:
        g = glyphs()
        legacy = ("choreoai> ", "› ", "❯ ", f"{g.prompt} ", f"  {g.prompt} ")
        glyph = message if message and message not in legacy else ""
        if glyph:
            return session.prompt([("class:prompt", glyph)])
        return session.prompt([("class:prompt", f"  {g.prompt} ")])

    return _prompt


def make_live_toolbar(harness: Any) -> Callable[[], Any]:
    """Toolbar that shows model, cwd, and live budget for the REPL."""

    def _toolbar() -> Any:
        try:
            from prompt_toolkit.formatted_text import HTML, to_formatted_text
        except ImportError:
            return ""
        model = model_label(harness)
        path = short_cwd(harness.cwd)
        budget = budget_short(harness)
        gg = glyphs()
        sep = f'  <style fg="{TAUPE}">{gg.middot}</style>  '
        return to_formatted_text(
            HTML(
                f'  <b><style fg="{TERRACOTTA}">{model}</style></b>'
                f"{sep}"
                f'<style fg="{SAND}">{path}</style>'
                f"{sep}"
                f'<style fg="{TAUPE}">{budget}</style>'
                f"{sep}"
                f'<style fg="{TAUPE}">↵ send {gg.middot} Esc↵ newline '
                f"{gg.middot} /help {gg.middot} Ctrl+C quit</style>"
            )
        )

    return _toolbar
