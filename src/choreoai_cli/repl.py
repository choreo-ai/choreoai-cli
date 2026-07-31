"""Interactive REPL for the coding-agent harness.

Inline Claude-Code / Grok-style terminal UI: **rich** for streamed rendering
(markdown, syntax, tool cards, status) and **prompt_toolkit** for a framed
multiline input with history, slash completion, and a live bottom toolbar.

Full-screen / alt-screen TUIs are intentionally avoided so agent output can
stream into normal terminal scrollback.
"""

from __future__ import annotations

import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.status import Status
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from choreoai.core.events import Event, Subscriber

from choreoai_cli.harness import CodingHarness, RunResult

# ---------------------------------------------------------------------------
# Brand palette (truecolor; Rich / terminal may degrade gracefully)
# ---------------------------------------------------------------------------

TERRACOTTA = "#C06B4E"
TERRACOTTA_DEEP = "#A8583D"
SAND = "#F1EBE0"
TAUPE = "#B0A89C"

# Rough Claude Sonnet-class list prices for a soft cost estimate (USD / 1M toks).
_EST_INPUT_PER_M = 3.0
_EST_OUTPUT_PER_M = 15.0

SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help", "Show available commands"),
    ("/reset", "Clear session budget, shell approvals, and trace"),
    ("/exit", "Quit the REPL"),
]

# Tool display icons (compact, monochrome-friendly)
_TOOL_ICONS: dict[str, str] = {
    "read_file": "◎",
    "write_file": "✎",
    "list_dir": "▦",
    "run_shell": "›",
}


class ToolArgTracker:
    """FIFO of recent tool arg/result summaries for live UI cards.

    Tools are sequential in the agent loop, so a simple queue correlates
    instrumented invocations with subsequent ``tool_called`` events.
    """

    def __init__(self) -> None:
        self._pending: Deque[tuple[str, str]] = deque()
        self._results: Deque[tuple[str, str]] = deque()

    def push_args(self, tool_name: str, summary: str) -> None:
        self._pending.append((tool_name, summary))

    def push_result(self, tool_name: str, preview: str) -> None:
        self._results.append((tool_name, preview))

    def pop_args(self, tool_name: str) -> str | None:
        if self._pending and self._pending[0][0] == tool_name:
            return self._pending.popleft()[1]
        for i, (name, summary) in enumerate(self._pending):
            if name == tool_name:
                del self._pending[i]
                return summary
        return None

    def pop_result(self, tool_name: str) -> str | None:
        if self._results and self._results[0][0] == tool_name:
            return self._results.popleft()[1]
        for i, (name, preview) in enumerate(self._results):
            if name == tool_name:
                del self._results[i]
                return preview
        return None

    def clear(self) -> None:
        self._pending.clear()
        self._results.clear()


def summarize_tool_args(tool_name: str, kwargs: dict[str, Any]) -> str:
    """Pick the signature argument for a compact tool-card line."""
    if tool_name == "read_file":
        return str(kwargs.get("path", "") or "")
    if tool_name == "write_file":
        path = str(kwargs.get("path", "") or "")
        content = kwargs.get("content", "")
        n = len(content) if isinstance(content, str) else 0
        return f"{path}  ({n} chars)" if path else ""
    if tool_name == "list_dir":
        return str(kwargs.get("path", ".") or ".")
    if tool_name == "run_shell":
        cmd = str(kwargs.get("command", "") or "")
        return (cmd[:72] + "…") if len(cmd) > 72 else cmd
    # Generic fallback: first short string value
    for key in ("path", "command", "query", "file", "name"):
        if key in kwargs and kwargs[key] is not None:
            s = str(kwargs[key])
            return (s[:72] + "…") if len(s) > 72 else s
    if not kwargs:
        return ""
    bits = []
    for k, v in list(kwargs.items())[:3]:
        sv = str(v)
        if len(sv) > 40:
            sv = sv[:40] + "…"
        bits.append(f"{k}={sv}")
    return " ".join(bits)


def preview_tool_result(result: Any, *, limit: int = 80) -> str:
    """One-line preview of a tool return value."""
    text = str(result).replace("\r\n", "\n").replace("\r", "\n")
    first = text.split("\n", 1)[0].strip()
    if not first:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        first = lines[0] if lines else ""
    if len(first) > limit:
        return first[: limit - 1] + "…"
    return first


def instrument_tools_for_ui(
    tools: list[Any],
    tracker: ToolArgTracker,
) -> list[Any]:
    """Wrap StructuredTools so arg/result summaries feed the live UI."""
    from langchain_core.tools import StructuredTool

    wrapped: list[Any] = []
    for tool in tools:
        if not isinstance(tool, StructuredTool) or tool.func is None:
            wrapped.append(tool)
            continue

        orig = tool.func
        name = tool.name

        def _make(orig_fn: Callable[..., Any], tname: str) -> Callable[..., Any]:
            def _fn(*args: Any, **kwargs: Any) -> Any:
                # StructuredTool usually passes kwargs; tolerate positional.
                if args and not kwargs:
                    # Best-effort: single-arg tools
                    pass
                tracker.push_args(tname, summarize_tool_args(tname, kwargs))
                try:
                    result = orig_fn(*args, **kwargs)
                except Exception as exc:
                    tracker.push_result(tname, preview_tool_result(f"error: {exc}"))
                    raise
                tracker.push_result(tname, preview_tool_result(result))
                return result

            return _fn

        wrapped.append(
            StructuredTool.from_function(
                func=_make(orig, name),
                name=name,
                description=tool.description or name,
                args_schema=tool.args_schema,
            )
        )
    return wrapped


def _history_path() -> Path:
    """Default path for persistent input history (XDG-ish / home)."""
    base = os.environ.get("CHOREOAI_CLI_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".choreoai-cli"
    return root / "history"


def _model_label(harness: CodingHarness) -> str:
    model = getattr(harness.agent, "model", None)
    if model is None:
        return "—"
    for attr in ("model", "model_name", "model_id"):
        val = getattr(model, attr, None)
        if isinstance(val, str) and val:
            return val
    return type(model).__name__


def _short_cwd(cwd: Path, *, max_len: int = 48) -> str:
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
        return "…" + s[-(max_len - 1) :]
    return s


def _budget_short(harness: CodingHarness) -> str:
    try:
        snap = harness.budget.snapshot(context=harness.session_context)
        parts: list[str] = []
        for dim, cap in snap.caps.items():
            used = snap.consumed.get(dim, 0.0)
            parts.append(f"{dim} {used:g}/{cap:g}")
        return " · ".join(parts) if parts else "budget n/a"
    except Exception:
        return harness.budget_summary()


def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000.0 * _EST_INPUT_PER_M
        + output_tokens / 1_000_000.0 * _EST_OUTPUT_PER_M
    )


def _format_cost(usd: float) -> str:
    if usd <= 0:
        return "$0.00"
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.3f}"


def print_banner(console: Console, harness: CodingHarness) -> None:
    """Compact startup header: wordmark, version, cwd, model, hints."""
    from choreoai_cli import __version__

    title = Text()
    title.append("●", style=f"bold {TERRACOTTA}")
    title.append(" ")
    title.append("ChoreoAI", style=f"bold {SAND}")
    title.append("  ", style="")
    title.append(f"v{__version__}", style=f"dim {TAUPE}")

    meta = Text()
    meta.append("cwd", style=f"dim {TAUPE}")
    meta.append("  ", style="")
    meta.append(str(harness.cwd), style=SAND)
    meta.append("\n", style="")
    meta.append("model", style=f"dim {TAUPE}")
    meta.append("  ", style="")
    meta.append(_model_label(harness), style=SAND)

    hint = Text(
        "/help for commands · Ctrl+C to quit",
        style=f"dim {TAUPE}",
    )

    body = Group(title, Text(""), meta, Text(""), hint)
    console.print(
        Panel(
            body,
            border_style=TERRACOTTA,
            padding=(0, 1),
            expand=True,
        )
    )


def print_api_key_note(console: Console) -> None:
    """Friendly note when the Anthropic key is missing (shell still starts)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    note = Text()
    note.append("Note  ", style=f"bold {TERRACOTTA}")
    note.append(
        "ANTHROPIC_API_KEY is not set. Live model calls will fail; "
        "you can still explore /help and the shell. "
        "Offline tests inject a fake model.",
        style=TAUPE,
    )
    console.print(
        Panel(note, border_style=TAUPE, padding=(0, 1), expand=True)
    )


def print_help(console: Console) -> None:
    """Render slash-command help as a clean table."""
    table = Table(
        show_header=True,
        header_style=f"bold {TERRACOTTA}",
        border_style=TAUPE,
        box=None,
        padding=(0, 2),
        expand=False,
    )
    table.add_column("Command", style=f"bold {SAND}")
    table.add_column("Description", style=TAUPE)
    for cmd, desc in SLASH_COMMANDS:
        table.add_row(cmd, desc)

    console.print()
    console.print(Text("Commands", style=f"bold {SAND}"))
    console.print(table)
    console.print()
    tips = Text()
    tips.append("Input", style=f"bold {SAND}")
    tips.append("\n  ", style="")
    tips.append("Enter", style=SAND)
    tips.append("  send     ", style=TAUPE)
    tips.append("Esc+Enter", style=SAND)
    tips.append(" / ", style=TAUPE)
    tips.append("Shift+Enter", style=SAND)
    tips.append("  newline\n", style=TAUPE)
    tips.append("  Up/Down", style=SAND)
    tips.append("  history     ", style=TAUPE)
    tips.append("Ctrl+C", style=SAND)
    tips.append("  quit\n", style=TAUPE)
    tips.append("\nShell approval", style=f"bold {SAND}")
    tips.append(" (when not --auto)\n", style=TAUPE)
    tips.append(
        "  y / yes · n / no · always / a · deny <pattern>\n",
        style=TAUPE,
    )
    tips.append(
        "\nAnything else is sent to the coding agent as an instruction.",
        style=TAUPE,
    )
    console.print(tips)
    console.print()


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
            # Only complete when the buffer looks like a slash command line.
            if not text.startswith("/"):
                return
            # Don't complete mid-sentence after the first token.
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

    # Enter submits; Esc+Enter / Ctrl+J insert a newline (Claude-Code style).
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

    # Shift+Enter where the terminal reports it (often as escape sequence).
    try:

        @kb.add("s-enter")
        def _newline_shift(event: Any) -> None:
            event.current_buffer.insert_text("\n")
    except Exception:
        pass

    def _default_toolbar() -> Any:
        model = model_name or "model"
        path = _short_cwd(cwd) if cwd is not None else "."
        return to_formatted_text(
            HTML(
                f"<b><style fg=\"{TERRACOTTA}\">{model}</style></b>"
                f" <style fg=\"{TAUPE}\">·</style> "
                f"<style fg=\"{SAND}\">{path}</style>"
                f" <style fg=\"{TAUPE}\">·</style> "
                f"<style fg=\"{TAUPE}\">↵ send · Esc↵ newline · /help · Ctrl+C quit</style>"
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
            f'<style fg="{TAUPE}">Message the agent…  (/ for commands)</style>'
        ),
    )

    def _prompt(message: str = "") -> str:
        # Ignore the legacy prompt string; we always use the branded glyph.
        glyph = message if message and message not in ("choreoai> ", "› ", "❯ ") else ""
        if glyph:
            return session.prompt([("class:prompt", glyph)])
        return session.prompt([("class:prompt", "❯ ")])

    return _prompt


class LiveEventSubscriber(Subscriber):
    """Stream tool-call (and related) events as compact Claude-Code-style cards.

    Optionally drives a rich ``Status`` spinner so the user sees activity while
    the model is thinking between events.
    """

    name = "live_repl"

    def __init__(
        self,
        console: Console,
        *,
        name: str = "live_repl",
        status: Status | None = None,
        arg_tracker: ToolArgTracker | None = None,
    ) -> None:
        self.name = name
        self.console = console
        self._status = status
        self._arg_tracker = arg_tracker
        self.tool_count = 0
        self.llm_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.steps = 0

    def bind_status(self, status: Status | None) -> None:
        """Attach or detach a Status spinner used during a single turn."""
        self._status = status

    def bind_arg_tracker(self, tracker: ToolArgTracker | None) -> None:
        self._arg_tracker = tracker

    def reset_turn_stats(self) -> None:
        self.tool_count = 0
        self.llm_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.steps = 0
        if self._arg_tracker is not None:
            self._arg_tracker.clear()

    def _pause_status(self) -> None:
        if self._status is not None:
            self._status.stop()

    def _resume_status(self, message: str = "orchestrating…") -> None:
        if self._status is not None:
            self._status.update(f"[{TERRACOTTA}]{message}[/{TERRACOTTA}]")
            self._status.start()

    def _tool_icon(self, tool_name: str) -> str:
        return _TOOL_ICONS.get(tool_name, "●")

    def _render_tool_card(
        self,
        *,
        tool_name: str,
        ok: bool,
        ms: float | int | None,
        arg_summary: str | None,
        result_preview: str | None,
        err: str | None,
    ) -> None:
        """Print one aligned tool line into scrollback (no Live wipe)."""
        ms_s = f"{ms:.0f}ms" if isinstance(ms, (int, float)) else "—"
        mark = "✔" if ok else "✗"
        mark_style = "green" if ok else "red"
        icon = self._tool_icon(tool_name)

        line = Text()
        line.append("  ")
        line.append(icon, style=TERRACOTTA if ok else "red")
        line.append(" ")
        line.append(f"{tool_name:<12}", style="bold")
        if arg_summary:
            # Key argument, dim — the Claude-Code signature look
            display_arg = arg_summary if len(arg_summary) <= 56 else arg_summary[:55] + "…"
            line.append(display_arg, style=f"dim {TAUPE}")

        # Right-side status: pad lightly then mark + time
        line.append("  ")
        line.append(mark, style=mark_style)
        line.append(" ")
        line.append(ms_s, style=f"dim {TAUPE}")

        self.console.print(line)

        # Optional second line: short result / error preview
        preview = err if (not ok and err) else result_preview
        if preview:
            prev = Text()
            prev.append("     ", style="")
            style = "red" if not ok else f"dim {TAUPE}"
            text = preview if len(preview) <= 100 else preview[:99] + "…"
            prev.append(text, style=style)
            self.console.print(prev)

    async def on_event(self, event: Event) -> None:
        etype = getattr(event, "type", None)

        if etype == "tool_called":
            self.tool_count += 1
            tool_name = getattr(event, "tool_name", "?") or "?"
            ok = bool(getattr(event, "success", False))
            ms = getattr(event, "duration_ms", None)
            err = getattr(event, "error", None)

            meta = getattr(event, "metadata", None) or {}
            arg_summary: str | None = None
            result_preview: str | None = None
            if isinstance(meta, dict):
                for key in ("args_summary", "input_summary"):
                    val = meta.get(key)
                    if val:
                        arg_summary = str(val)
                        break
                for key in ("result_summary", "output_summary"):
                    val = meta.get(key)
                    if val:
                        result_preview = str(val)
                        break

            if self._arg_tracker is not None:
                if not arg_summary:
                    arg_summary = self._arg_tracker.pop_args(tool_name)
                if not result_preview:
                    result_preview = self._arg_tracker.pop_result(tool_name)

            self._pause_status()
            self._render_tool_card(
                tool_name=tool_name,
                ok=ok,
                ms=ms,
                arg_summary=arg_summary,
                result_preview=result_preview,
                err=str(err) if err else None,
            )
            self._resume_status("orchestrating…")

        elif etype == "llm_called":
            self.llm_count += 1
            ok = getattr(event, "success", True)
            ms = getattr(event, "duration_ms", None)
            ms_s = f"{ms:.0f}ms" if isinstance(ms, (int, float)) else ""
            model = getattr(event, "model", None) or "model"
            in_tok = getattr(event, "input_tokens", None)
            out_tok = getattr(event, "output_tokens", None)
            if isinstance(in_tok, int):
                self.total_input_tokens += in_tok
            if isinstance(out_tok, int):
                self.total_output_tokens += out_tok

            if not ok:
                err = getattr(event, "error", None) or "llm error"
                self._pause_status()
                line = Text()
                line.append("  ● ", style="yellow")
                line.append("llm", style="yellow")
                line.append(f"  fail — {err}", style=TAUPE)
                self.console.print(line)
                self._resume_status("orchestrating…")
            else:
                # Quiet success — usage lands in the turn footer.
                bits = Text()
                bits.append("  · ", style=f"dim {TAUPE}")
                bits.append(str(model), style=f"dim {TAUPE}")
                if ms_s:
                    bits.append(f"  {ms_s}", style=f"dim {TAUPE}")
                tok_parts = []
                if isinstance(in_tok, int):
                    tok_parts.append(f"in={in_tok}")
                if isinstance(out_tok, int):
                    tok_parts.append(f"out={out_tok}")
                if tok_parts:
                    bits.append(f"  {' '.join(tok_parts)}", style=f"dim {TAUPE}")
                self._pause_status()
                self.console.print(bits)
                self._resume_status("orchestrating…")

        elif etype == "run_started":
            self._resume_status("orchestrating…")

        elif etype == "run_finished":
            status = getattr(event, "status", "?")
            self._pause_status()
            if status and status not in ("ok",):
                self.console.print(
                    Text(f"  run finished ({status})", style=f"dim {TAUPE}")
                )

        elif etype == "step_finished":
            self.steps += 1


def _looks_like_code(text: str) -> bool:
    """Heuristic: treat as code block when it has no prose structure."""
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("```"):
        return False  # Markdown fences — let Markdown renderer handle it
    lines = stripped.splitlines()
    if len(lines) < 2:
        return False
    code_markers = (
        "def ",
        "class ",
        "import ",
        "from ",
        "function ",
        "const ",
        "let ",
        "var ",
        "#!/",
        "package ",
        "fn ",
        "pub ",
    )
    first = lines[0].lstrip()
    return any(first.startswith(m) for m in code_markers) or (
        sum(
            1
            for ln in lines
            if ln.startswith((" ", "\t")) or ln.rstrip().endswith((";", "{", "}"))
        )
        >= max(2, len(lines) // 2)
    )


def _render_answer_body(text: str) -> Any:
    """Choose Markdown vs Syntax highlighting for the final answer."""
    if not text.strip():
        return Text("(no output)", style=f"dim {TAUPE}")
    if _looks_like_code(text):
        lexer = "python"
        first = text.lstrip()
        if first.startswith(("{", "[")):
            lexer = "json"
        elif first.startswith("<"):
            lexer = "html"
        elif "fn " in first or first.startswith("use "):
            lexer = "rust"
        return Syntax(text, lexer, theme="monokai", line_numbers=False, word_wrap=True)
    return Markdown(text)


def print_result(
    console: Console,
    harness: CodingHarness,
    result: RunResult,
    *,
    live: LiveEventSubscriber | None = None,
    elapsed_s: float | None = None,
) -> None:
    """Render the assistant answer plus a dim turn footer (tokens / budget / time)."""
    text = result.output if result.output is not None else "(no output)"
    if not isinstance(text, str):
        text = str(text)

    # Assistant marker + live Markdown body (no heavy panel wipe of scrollback).
    header = Text()
    header.append("●", style=f"bold {TERRACOTTA}")
    header.append(" ", style="")
    header.append("Answer", style=f"bold {SAND}")
    console.print()
    console.print(header)
    console.print(_render_answer_body(text))
    console.print()

    snap = result.budget_snapshot
    budget_parts: list[str] = []
    if snap is not None:
        for dim, cap in snap.caps.items():
            used = snap.consumed.get(dim, 0.0)
            remaining = cap - used
            budget_parts.append(f"{dim} {used:g}/{cap:g} (left {remaining:g})")
    else:
        budget_parts.append(harness.budget_summary())

    in_tok = live.total_input_tokens if live is not None else 0
    out_tok = live.total_output_tokens if live is not None else 0
    tools_n = live.tool_count if live is not None else 0
    llm_n = live.llm_count if live is not None else 0

    footer = Text()
    footer.append("  ", style="")
    parts: list[str] = []
    if in_tok or out_tok:
        parts.append(f"tokens {in_tok}↑ {out_tok}↓")
        parts.append(f"est {_format_cost(_estimate_cost_usd(in_tok, out_tok))}")
    if tools_n or llm_n:
        parts.append(f"tools={tools_n} llm={llm_n}")
    if budget_parts:
        # Prefix so "budget" remains easy to grep in tests / logs.
        parts.append("budget " + " · ".join(budget_parts))
    if elapsed_s is not None:
        if elapsed_s < 10:
            parts.append(f"{elapsed_s:.1f}s")
        else:
            parts.append(f"{elapsed_s:.0f}s")
    parts.append(f"trace: {harness.trace_summary()}")

    footer.append(" · ".join(parts), style=f"dim {TAUPE}")
    console.print(footer)
    console.print(Rule(style=f"dim {TAUPE}"))


# Back-compat alias used by __main__ and older tests.
_print_result = print_result


def run_repl(
    harness: CodingHarness,
    *,
    console: Console | None = None,
    input_fn: Any = None,
    live_stream: bool = True,
    use_spinner: bool = True,
    multiline: bool = True,
    history_file: Path | None | bool = None,
) -> int:
    """Run the interactive loop until /exit or EOF. Returns process exit code.

    Parameters
    ----------
    input_fn:
        Optional ``(prompt) -> str`` override (used by tests). When omitted,
        builds a prompt_toolkit session when stdin is a TTY, else ``input``.
    live_stream:
        Subscribe a ``LiveEventSubscriber`` for as-it-happens tool rendering.
    use_spinner:
        Show a rich Status spinner while the agent runs (disabled in tests /
        non-TTY).
    multiline:
        Enable prompt_toolkit multiline buffer (Enter sends; Esc+Enter newline).
    history_file:
        Path for history, ``None`` for default ``~/.choreoai-cli/history``,
        or ``False`` for in-memory only.
    """
    console = console or Console()
    cwd = harness.cwd

    # Instrument tools once so tool cards can show key args + result previews.
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

    if input_fn is None:
        if history_file is False:
            hist: Path | None = None
        elif history_file is None:
            hist = _history_path()
        else:
            hist = history_file
        force_plain = not console.is_terminal

        def _toolbar() -> Any:
            try:
                from prompt_toolkit.formatted_text import HTML, to_formatted_text
            except ImportError:
                return ""
            model = _model_label(harness)
            path = _short_cwd(cwd)
            budget = _budget_short(harness)
            return to_formatted_text(
                HTML(
                    f"<b><style fg=\"{TERRACOTTA}\">{model}</style></b>"
                    f" <style fg=\"{TAUPE}\">·</style> "
                    f"<style fg=\"{SAND}\">{path}</style>"
                    f" <style fg=\"{TAUPE}\">·</style> "
                    f"<style fg=\"{TAUPE}\">{budget}</style>"
                    f" <style fg=\"{TAUPE}\">·</style> "
                    f"<style fg=\"{TAUPE}\">↵ send · Esc↵ newline · /help · Ctrl+C quit</style>"
                )
            )

        input_fn = make_prompt_fn(
            history_file=hist,
            multiline=multiline,
            force_plain=force_plain,
            toolbar_fn=_toolbar if not force_plain else None,
            model_name=_model_label(harness),
            cwd=cwd,
        )

    print_banner(console, harness)
    print_api_key_note(console)

    live: LiveEventSubscriber | None = None
    if live_stream:
        live = LiveEventSubscriber(console, arg_tracker=arg_tracker)
        harness.add_subscriber(live)

    spinner_ok = use_spinner and console.is_terminal and not console.quiet

    while True:
        try:
            line = input_fn("❯ ")
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
            harness.reset_session()
            if live is not None:
                live.reset_turn_stats()
            if arg_tracker is not None:
                arg_tracker.clear()
            console.print(
                Text(
                    "Session reset: budget ledger, shell approvals, and trace cleared.",
                    style=f"dim {TAUPE}",
                )
            )
            continue
        if text.startswith("/"):
            console.print(
                Text(f"Unknown command: {text}. Try /help.", style="yellow")
            )
            continue

        if live is not None:
            live.reset_turn_stats()

        t0 = time.perf_counter()
        try:
            if spinner_ok:
                with console.status(
                    f"[{TERRACOTTA}]orchestrating…[/{TERRACOTTA}]",
                    spinner="dots",
                ) as status:
                    if live is not None:
                        live.bind_status(status)
                    try:
                        result = harness.run(text)
                    finally:
                        if live is not None:
                            live.bind_status(None)
            else:
                result = harness.run(text)
        except KeyboardInterrupt:
            console.print()
            console.print(Text("Turn cancelled.", style=f"dim {TAUPE}"))
            continue
        except Exception as exc:
            console.print(Text(f"Error: {exc}", style="red"))
            continue

        elapsed = time.perf_counter() - t0
        print_result(console, harness, result, live=live, elapsed_s=elapsed)

    console.print(Text("bye", style=f"dim {TAUPE}"))
    return 0


def build_live_harness(
    *,
    cwd: Path | None = None,
    auto: bool = False,
    max_steps: int = 10,
    step_budget: float = 20.0,
) -> CodingHarness:
    """Build a harness with the default Claude model (needs ANTHROPIC_API_KEY)."""
    from choreoai.models import get_default_model

    model = get_default_model()
    harness = CodingHarness.create(
        model=model,
        cwd=cwd,
        auto=auto,
        max_steps=max_steps,
        step_budget=step_budget,
    )
    # Pre-install arg tracker so tool cards have key arguments on first turn.
    tracker = ToolArgTracker()
    harness.tool_arg_tracker = tracker  # type: ignore[attr-defined]
    try:
        tools = list(harness.agent.tools)
        instrumented = instrument_tools_for_ui(tools, tracker)
        harness.agent.tools = instrumented
        harness.agent._tool_map = {t.name: t for t in instrumented}  # noqa: SLF001
    except Exception:
        pass
    return harness
