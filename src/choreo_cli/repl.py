"""Interactive REPL for the coding-agent harness.

Uses **rich** for Claude-Code-style streamed rendering (panels, markdown,
syntax, spinners) and **prompt_toolkit** for a polished input line (history,
multiline). Full-screen Textual TUIs are intentionally avoided so agent output
can stream line-by-line into a normal terminal scrollback.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.status import Status
from rich.syntax import Syntax
from rich.text import Text

from choreo.core.events import Event, Subscriber

from choreo_cli.harness import CodingHarness, RunResult

HELP_TEXT = """\
Commands:
  /help   Show this help
  /reset  Clear session budget ledger, shell approvals, and trace
  /exit   Quit the REPL

Anything else is sent to the coding agent as an instruction.

Input:
  Enter           submit (single-line mode)
  Esc then Enter  submit (when multiline is enabled)
  Ctrl+C / Ctrl+D quit
  Up/Down         history (prompt_toolkit)

Shell approval (when not --auto):
  y / yes           allow this command once
  n / no            deny this command once
  always / a        allow all shell commands for this session
  deny <pattern>    reject commands containing <pattern> for this session
"""


def _history_path() -> Path:
    """Default path for persistent input history (XDG-ish / home)."""
    base = os.environ.get("CHOREOAI_CLI_HOME")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".choreoai-cli"
    return root / "history"


def make_prompt_fn(
    *,
    history_file: Path | None = None,
    multiline: bool = True,
    force_plain: bool = False,
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
        from prompt_toolkit.history import FileHistory, InMemoryHistory
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

    style = Style.from_dict(
        {
            "prompt": "ansicyan bold",
            "continuation": "ansibrightblack",
        }
    )
    session: PromptSession[str] = PromptSession(
        history=history,
        auto_suggest=AutoSuggestFromHistory(),
        enable_history_search=True,
        multiline=multiline,
        prompt_continuation=lambda width, line_number, is_soft_wrap: "... ",
        style=style,
    )

    def _prompt(message: str = "") -> str:
        return session.prompt([("class:prompt", message)])

    return _prompt


class LiveEventSubscriber(Subscriber):
    """Stream tool-call (and related) events to the console as they arrive.

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
    ) -> None:
        self.name = name
        self.console = console
        self._status = status
        self.tool_count = 0
        self.llm_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def bind_status(self, status: Status | None) -> None:
        """Attach or detach a Status spinner used during a single turn."""
        self._status = status

    def reset_turn_stats(self) -> None:
        self.tool_count = 0
        self.llm_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def _pause_status(self) -> None:
        if self._status is not None:
            self._status.stop()

    def _resume_status(self, message: str = "thinking…") -> None:
        if self._status is not None:
            self._status.update(f"[bold cyan]{message}[/bold cyan]")
            self._status.start()

    async def on_event(self, event: Event) -> None:
        etype = getattr(event, "type", None)

        if etype == "tool_called":
            self.tool_count += 1
            tool_name = getattr(event, "tool_name", "?")
            ok = getattr(event, "success", False)
            ms = getattr(event, "duration_ms", None)
            ms_s = f"{ms:.0f}ms" if isinstance(ms, (int, float)) else "—"
            err = getattr(event, "error", None)
            status_label = "ok" if ok else "fail"
            style = "green" if ok else "red"

            meta = getattr(event, "metadata", None) or {}
            detail_bits: list[str] = []
            for key in ("args_summary", "input_summary", "result_summary", "output_summary"):
                val = meta.get(key) if isinstance(meta, dict) else None
                if val:
                    detail_bits.append(str(val))
            if err:
                detail_bits.append(str(err))

            body = Text()
            body.append(tool_name, style="bold")
            body.append(f"  [{status_label}]", style=style)
            body.append(f"  {ms_s}", style="dim")
            if detail_bits:
                body.append("\n")
                body.append("  ".join(detail_bits)[:400], style="dim")

            self._pause_status()
            self.console.print(
                Panel(
                    body,
                    title=f"[bold]tool[/bold] #{self.tool_count}",
                    border_style="cyan" if ok else "red",
                    padding=(0, 1),
                )
            )
            self._resume_status("thinking…")

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
                self.console.print(f"[yellow]llm[/yellow] fail — {err}")
                self._resume_status("thinking…")
            else:
                # Quiet success line; full usage is in the turn footer.
                bits = [f"[dim]llm[/dim] {model}"]
                if ms_s:
                    bits.append(f"[dim]{ms_s}[/dim]")
                tok_parts = []
                if isinstance(in_tok, int):
                    tok_parts.append(f"in={in_tok}")
                if isinstance(out_tok, int):
                    tok_parts.append(f"out={out_tok}")
                if tok_parts:
                    bits.append(f"[dim]{' '.join(tok_parts)}[/dim]")
                self._pause_status()
                self.console.print("  ".join(bits))
                self._resume_status("thinking…")

        elif etype == "run_started":
            self._resume_status("run started…")

        elif etype == "run_finished":
            status = getattr(event, "status", "?")
            self._pause_status()
            self.console.print(f"[dim]run finished ({status})[/dim]")

        elif etype == "step_finished":
            # Keep noise low; tool/llm events already cover the interesting bits.
            pass


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
        sum(1 for ln in lines if ln.startswith((" ", "\t")) or ln.rstrip().endswith((";", "{", "}")))
        >= max(2, len(lines) // 2)
    )


def _render_answer_body(text: str) -> Any:
    """Choose Markdown vs Syntax highlighting for the final answer panel."""
    if not text.strip():
        return Text("(no output)", style="dim")
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
) -> None:
    """Render the final answer panel plus budget/usage footer for one turn."""
    text = result.output if result.output is not None else "(no output)"
    if not isinstance(text, str):
        text = str(text)

    console.print(
        Panel(
            _render_answer_body(text),
            title="[bold]Answer[/bold]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    snap = result.budget_snapshot
    budget_parts: list[str] = []
    if snap is not None:
        for dim, cap in snap.caps.items():
            used = snap.consumed.get(dim, 0.0)
            budget_parts.append(f"{dim} {used:g}/{cap:g}")
    else:
        budget_parts.append(harness.budget_summary())

    footer = Text()
    footer.append("budget: ", style="dim")
    footer.append(", ".join(budget_parts) if budget_parts else "n/a", style="dim")

    if live is not None:
        if live.tool_count or live.llm_count:
            footer.append("  |  ", style="dim")
            footer.append(
                f"tools={live.tool_count} llm={live.llm_count}",
                style="dim",
            )
        if live.total_input_tokens or live.total_output_tokens:
            footer.append("  |  ", style="dim")
            footer.append(
                f"tokens in={live.total_input_tokens} out={live.total_output_tokens}",
                style="dim",
            )

    footer.append("  |  ", style="dim")
    footer.append(f"trace: {harness.trace_summary()}", style="dim")
    console.print(footer)


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
        Enable prompt_toolkit multiline input (Esc+Enter to submit).
    history_file:
        Path for history, ``None`` for default ``~/.choreoai-cli/history``,
        or ``False`` for in-memory only.
    """
    console = console or Console()
    cwd = harness.cwd

    if input_fn is None:
        if history_file is False:
            hist: Path | None = None
        elif history_file is None:
            hist = _history_path()
        else:
            hist = history_file
        # When console is quiet / not a real TTY, force plain input.
        force_plain = not console.is_terminal
        input_fn = make_prompt_fn(
            history_file=hist,
            multiline=multiline,
            force_plain=force_plain,
        )

    banner = Group(
        Text("choreoai-cli coding agent", style="bold green"),
        Text(f"cwd: {cwd}", style="dim"),
        Text("Type /help for commands, /exit to quit.", style="dim"),
    )
    console.print(Panel(banner, title="choreoai-cli", border_style="green"))

    live: LiveEventSubscriber | None = None
    if live_stream:
        live = LiveEventSubscriber(console)
        harness.add_subscriber(live)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[yellow]Note: ANTHROPIC_API_KEY is not set. "
            "Live model calls will fail; offline/tests inject a fake model.[/yellow]"
        )

    spinner_ok = (
        use_spinner
        and console.is_terminal
        and not console.quiet
    )

    while True:
        try:
            line = input_fn("choreoai> ")
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
            if live is not None:
                live.reset_turn_stats()
            console.print(
                "[dim]Session reset: budget ledger, shell approvals, and trace cleared.[/dim]"
            )
            continue
        if text.startswith("/"):
            console.print(f"[yellow]Unknown command: {text}. Try /help.[/yellow]")
            continue

        if live is not None:
            live.reset_turn_stats()

        try:
            if spinner_ok:
                with console.status("[bold cyan]thinking…[/bold cyan]", spinner="dots") as status:
                    if live is not None:
                        live.bind_status(status)
                    try:
                        result = harness.run(text)
                    finally:
                        if live is not None:
                            live.bind_status(None)
            else:
                result = harness.run(text)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")
            continue

        print_result(console, harness, result, live=live)

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
