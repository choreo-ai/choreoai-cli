"""Tests for UTF-8 stdio setup and ASCII glyph fallback."""

from __future__ import annotations

import io

from rich.console import Console

from choreoai_cli.stdio import (
    ASCII_GLYPHS,
    Glyphs,
    configure_stdio_utf8,
    make_console,
    stream_supports_unicode,
)


def test_stream_supports_unicode_utf8() -> None:
    class Utf8:
        encoding = "utf-8"

    assert stream_supports_unicode(Utf8()) is True


def test_stream_supports_unicode_cp1252() -> None:
    class Cp1252:
        encoding = "cp1252"

    assert stream_supports_unicode(Cp1252()) is False


def test_stream_supports_unicode_ascii() -> None:
    class Ascii:
        encoding = "ascii"

    assert stream_supports_unicode(Ascii()) is False


def test_configure_stdio_utf8_is_idempotent() -> None:
    configure_stdio_utf8()
    configure_stdio_utf8()  # must not raise


def test_make_console_disables_legacy_windows() -> None:
    buf = io.StringIO()
    console = make_console(file=buf, force_terminal=False, width=40)
    assert console.legacy_windows is False


def test_ascii_glyphs_are_encodable_on_cp1252() -> None:
    blob = "".join(
        [
            ASCII_GLYPHS.bullet,
            ASCII_GLYPHS.prompt,
            ASCII_GLYPHS.ok,
            ASCII_GLYPHS.fail,
            ASCII_GLYPHS.ellipsis,
            ASCII_GLYPHS.emdash,
            ASCII_GLYPHS.middot,
            *ASCII_GLYPHS.tool_icons().values(),
        ]
    )
    blob.encode("cp1252")
    blob.encode("ascii")


def test_banner_renders_with_ascii_glyphs(monkeypatch) -> None:
    import choreoai_cli.ui.theme as theme
    from choreoai_cli.ui.header import print_banner
    from pathlib import Path

    monkeypatch.setattr(theme, "_unicode_ok", False)
    monkeypatch.setattr(theme, "_glyphs", ASCII_GLYPHS)

    buf = io.StringIO()
    console = Console(
        file=buf, force_terminal=False, width=60, legacy_windows=False, safe_box=True
    )

    class Harness:
        cwd = Path(".")

        class agent:
            model = None

    print_banner(console, Harness())  # type: ignore[arg-type]
    out = buf.getvalue()
    assert "ChoreoAI" in out
    assert ASCII_GLYPHS.bullet in out
    assert "●" not in out


def test_default_glyphs_are_unicode() -> None:
    fancy = Glyphs()
    assert fancy.bullet == "●"
    assert fancy.prompt == "❯"
    assert fancy.ok == "✔"
