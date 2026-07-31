"""Tool-call cards and LiveEventSubscriber for inline scrollback UI."""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Deque

from rich.console import Console
from rich.padding import Padding
from rich.status import Status
from rich.table import Table
from rich.text import Text

from choreoai.core.events import Event, Subscriber

from choreoai_cli.engine.events import ToolCallEvent, TurnStats, adapt_choreoai_event
from choreoai_cli.ui.theme import GUTTER, TAUPE, TERRACOTTA, glyphs, gutter_pad


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
        g = glyphs()
        return (cmd[:72] + g.ellipsis) if len(cmd) > 72 else cmd
    ell = glyphs().ellipsis
    for key in ("path", "command", "query", "file", "name"):
        if key in kwargs and kwargs[key] is not None:
            s = str(kwargs[key])
            return (s[:72] + ell) if len(s) > 72 else s
    if not kwargs:
        return ""
    bits = []
    for k, v in list(kwargs.items())[:3]:
        sv = str(v)
        if len(sv) > 40:
            sv = sv[:40] + ell
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
        return first[: limit - 1] + glyphs().ellipsis
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
                tracker.push_args(tname, summarize_tool_args(tname, kwargs))
                try:
                    result = orig_fn(*args, **kwargs)
                except Exception as exc:
                    tracker.push_result(tname, preview_tool_result(f"error: {exc}"))
                    raise
                tracker.push_result(tname, preview_tool_result(result))
                return result

            return _fn

        new_tool = StructuredTool.from_function(
            func=_make(orig, name),
            name=name,
            description=tool.description or name,
            args_schema=tool.args_schema,
        )
        # Preserve safety metadata from the original tool.
        try:
            from choreoai_cli.tools.base import copy_safety

            copy_safety(tool, new_tool)
        except Exception:
            pass
        wrapped.append(new_tool)
    return wrapped


class LiveEventSubscriber(Subscriber):
    """Stream tool-call events as compact Claude-Code-style cards.

    Optionally drives a rich ``Status`` spinner so the user sees activity while
    the model is thinking between events. Internally uses the typed event
    adapter so cards stay consistent with ``QueryEngine.submit()`` events.
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
        self.stats = TurnStats()
        # Back-compat attributes used by print_result / tests.
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
        self.stats.reset()
        self.tool_count = 0
        self.llm_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.steps = 0
        if self._arg_tracker is not None:
            self._arg_tracker.clear()

    def _sync_stats_attrs(self) -> None:
        self.tool_count = self.stats.tool_count
        self.llm_count = self.stats.llm_count
        self.total_input_tokens = self.stats.total_input_tokens
        self.total_output_tokens = self.stats.total_output_tokens
        self.steps = self.stats.steps

    def _pause_status(self) -> None:
        if self._status is not None:
            self._status.stop()

    def _resume_status(self, message: str | None = None) -> None:
        if self._status is not None:
            if message is None:
                message = f"orchestrating{glyphs().ellipsis}"
            self._status.update(f"[{TERRACOTTA}]{message}[/{TERRACOTTA}]")
            self._status.start()

    def _tool_icon(self, tool_name: str) -> str:
        g = glyphs()
        return g.tool_icons().get(tool_name, g.icon_default)

    def render_tool_card(
        self,
        *,
        tool_name: str,
        ok: bool,
        ms: float | int | None,
        arg_summary: str | None,
        result_preview: str | None,
        err: str | None,
        tool_index: int = 1,
    ) -> None:
        """Print one aligned tool line into scrollback (no Live wipe)."""
        g = glyphs()
        ms_s = f"{ms:.0f}ms" if isinstance(ms, (int, float)) else g.emdash
        mark = g.ok if ok else g.fail
        mark_style = "green" if ok else "red"
        icon = self._tool_icon(tool_name)

        display_arg = ""
        if arg_summary:
            display_arg = (
                arg_summary
                if len(arg_summary) <= 48
                else arg_summary[:47] + g.ellipsis
            )

        grid = Table.grid(padding=(0, 1), pad_edge=False, expand=False)
        grid.add_column(width=2, no_wrap=True, justify="left")
        grid.add_column(width=12, no_wrap=True, justify="left", style="bold")
        grid.add_column(
            width=48,
            no_wrap=True,
            overflow="ellipsis",
            justify="left",
            style=f"dim {TAUPE}",
        )
        grid.add_column(width=2, no_wrap=True, justify="center")
        grid.add_column(
            width=7, no_wrap=True, justify="right", style=f"dim {TAUPE}"
        )

        mark_text = Text(mark, style=mark_style)
        icon_text = Text(icon, style=TERRACOTTA if ok else "red")
        grid.add_row(icon_text, tool_name, display_arg, mark_text, ms_s)

        if tool_index == 1:
            self.console.print()
        self.console.print(gutter_pad(grid))

        preview = err if (not ok and err) else result_preview
        if preview:
            style = "red" if not ok else f"dim {TAUPE}"
            text = preview if len(preview) <= 100 else preview[:99] + g.ellipsis
            prev = Text(text, style=style)
            self.console.print(Padding(prev, (0, 0, 0, GUTTER + 3 + 13)))

    def _render_tool_card(self, **kwargs: Any) -> None:
        """Internal alias used by on_event."""
        kwargs.setdefault("tool_index", self.tool_count)
        self.render_tool_card(**kwargs)

    def render_llm_line(
        self,
        *,
        model: str,
        ok: bool,
        ms: float | int | None,
        in_tok: int | None,
        out_tok: int | None,
        error: str | None = None,
    ) -> None:
        g = glyphs()
        ms_s = f"{ms:.0f}ms" if isinstance(ms, (int, float)) else ""
        if not ok:
            err = error or "llm error"
            line = Text()
            line.append(f"{g.bullet} ", style="yellow")
            line.append("llm", style="yellow")
            line.append(f"  fail {g.emdash} {err}", style=TAUPE)
            self.console.print(gutter_pad(line))
            return
        bits = Text()
        bits.append(f"{g.middot} ", style=f"dim {TAUPE}")
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
        self.console.print(gutter_pad(bits))

    async def on_event(self, event: Event) -> None:
        adapted = adapt_choreoai_event(event, stats=self.stats)
        self._sync_stats_attrs()

        etype = getattr(event, "type", None)

        if isinstance(adapted, ToolCallEvent):
            arg_summary = adapted.arg_summary
            result_preview = adapted.result_preview
            if self._arg_tracker is not None:
                if not arg_summary:
                    arg_summary = self._arg_tracker.pop_args(adapted.tool_name)
                if not result_preview:
                    result_preview = self._arg_tracker.pop_result(adapted.tool_name)

            self._pause_status()
            self._render_tool_card(
                tool_name=adapted.tool_name,
                ok=adapted.success,
                ms=adapted.duration_ms,
                arg_summary=arg_summary,
                result_preview=result_preview,
                err=adapted.error,
            )
            self._resume_status()
            return

        if adapted is not None and adapted.kind == "llm_call":
            self._pause_status()
            self.render_llm_line(
                model=getattr(adapted, "model", "model"),
                ok=bool(getattr(adapted, "success", True)),
                ms=getattr(adapted, "duration_ms", None),
                in_tok=getattr(adapted, "input_tokens", None),
                out_tok=getattr(adapted, "output_tokens", None),
                error=getattr(adapted, "error", None),
            )
            self._resume_status()
            return

        if etype == "run_started":
            self._resume_status()
        elif etype == "run_finished":
            status = getattr(event, "status", "?")
            self._pause_status()
            if status and status not in ("ok",):
                self.console.print(
                    gutter_pad(
                        Text(f"run finished ({status})", style=f"dim {TAUPE}")
                    )
                )
