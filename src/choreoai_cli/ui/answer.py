"""Streaming / final Markdown answer rendering."""

from __future__ import annotations

from typing import Any

from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

from choreoai_cli.ui.theme import TAUPE


def looks_like_code(text: str) -> bool:
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


def render_answer_body(text: str) -> Any:
    """Choose Markdown vs Syntax highlighting for the final answer."""
    if not text.strip():
        return Text("(no output)", style=f"dim {TAUPE}")
    if looks_like_code(text):
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


# Back-compat private aliases.
_looks_like_code = looks_like_code
_render_answer_body = render_answer_body
