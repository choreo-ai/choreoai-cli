"""Brand palette, glyphs (Unicode / ASCII fallback), and console factory.

On Windows the process stdout encoding is often cp1252, which cannot encode
brand glyphs (●, ❯, ✔, …). Rich may also take its legacy-Windows path and
route through the same codec. Configure streams for UTF-8 at startup and fall
back to ASCII symbols only when the encoding still cannot represent them.
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from typing import Any, TextIO

from rich.console import Console
from rich.padding import Padding

# ---------------------------------------------------------------------------
# Brand palette (truecolor; Rich / terminal may degrade gracefully)
# ---------------------------------------------------------------------------

TERRACOTTA = "#C06B4E"
TERRACOTTA_DEEP = "#A8583D"
SAND = "#F1EBE0"
TAUPE = "#B0A89C"

# Consistent left gutter so content is not jammed against the terminal edge.
GUTTER = 2

# Rough Claude Sonnet-class list prices for a soft cost estimate (USD / 1M toks).
EST_INPUT_PER_M = 3.0
EST_OUTPUT_PER_M = 15.0

# Glyphs that appear in the banner / tool cards / prompt — used as a probe.
_SENTINEL = "●❯✔✗…—·◎✎▦›"


def configure_stdio_utf8() -> None:
    """Force UTF-8 (with replace) on stdout and stderr when possible."""
    for name in ("stdout", "stderr"):
        stream: TextIO | None = getattr(sys, name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
                continue
            except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
                pass
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        try:
            wrapped = io.TextIOWrapper(
                buffer,
                encoding="utf-8",
                errors="replace",
                line_buffering=bool(getattr(stream, "line_buffering", True)),
                write_through=bool(getattr(stream, "write_through", False)),
            )
            setattr(sys, name, wrapped)
        except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
            pass


def stream_supports_unicode(stream: TextIO | None = None) -> bool:
    """Return True if *stream* can encode the brand glyph set."""
    stream = stream if stream is not None else sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        _SENTINEL.encode(encoding)
        return True
    except (LookupError, UnicodeEncodeError):
        return False


@dataclass(frozen=True)
class Glyphs:
    """Brand / UI symbols — Unicode when safe, ASCII otherwise."""

    bullet: str = "●"
    prompt: str = "❯"
    ok: str = "✔"
    fail: str = "✗"
    ellipsis: str = "…"
    emdash: str = "—"
    middot: str = "·"
    icon_read: str = "◎"
    icon_write: str = "✎"
    icon_list: str = "▦"
    icon_shell: str = "›"
    icon_default: str = "●"

    def tool_icons(self) -> dict[str, str]:
        return {
            "read_file": self.icon_read,
            "write_file": self.icon_write,
            "list_dir": self.icon_list,
            "run_shell": self.icon_shell,
        }


ASCII_GLYPHS = Glyphs(
    bullet="*",
    prompt=">",
    ok="[ok]",
    fail="[x]",
    ellipsis="...",
    emdash="-",
    middot="|",
    icon_read="o",
    icon_write="w",
    icon_list="#",
    icon_shell=">",
    icon_default="*",
)

_unicode_ok: bool | None = None
_glyphs: Glyphs | None = None


def init_output() -> bool:
    """Configure UTF-8 stdio and select glyph mode. Returns True if Unicode OK."""
    global _unicode_ok, _glyphs
    configure_stdio_utf8()
    _unicode_ok = stream_supports_unicode(sys.stdout)
    _glyphs = Glyphs() if _unicode_ok else ASCII_GLYPHS
    return _unicode_ok


def unicode_output_ok() -> bool:
    """Whether fancy glyphs should be used (after :func:`init_output`)."""
    if _unicode_ok is None:
        init_output()
    return bool(_unicode_ok)


def glyphs() -> Glyphs:
    """Active glyph set (Unicode or ASCII)."""
    if _glyphs is None:
        init_output()
    assert _glyphs is not None
    return _glyphs


def make_console(**kwargs: Any) -> Console:
    """Build a Rich Console that emits UTF-8 and never uses legacy Win32 print.

    ``legacy_windows=False`` is critical: with the default auto-detect, Rich
    routes through ``LegacyWindowsTerm`` which still encodes with the
    process code page (often cp1252) even after Python stream reconfigure.
    """
    if _unicode_ok is None:
        init_output()
    kwargs.setdefault("legacy_windows", False)
    # When the stream cannot encode box-drawing, Rich falls back safely.
    kwargs.setdefault("safe_box", True)
    return Console(**kwargs)


def gutter_pad(renderable: Any, *, top: int = 0, bottom: int = 0) -> Padding:
    """Apply the global left gutter (and optional vertical padding)."""
    return Padding(renderable, (top, 0, bottom, GUTTER))


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000.0 * EST_INPUT_PER_M
        + output_tokens / 1_000_000.0 * EST_OUTPUT_PER_M
    )


def format_cost(usd: float) -> str:
    if usd <= 0:
        return "$0.00"
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.3f}"
