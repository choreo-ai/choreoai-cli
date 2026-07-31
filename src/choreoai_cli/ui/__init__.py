"""Inline Rich + prompt_toolkit UI components."""

from choreoai_cli.ui.answer import looks_like_code, render_answer_body
from choreoai_cli.ui.footer import print_result
from choreoai_cli.ui.header import model_label, print_api_key_note, print_banner, short_cwd
from choreoai_cli.ui.help import HELP_TEXT, SLASH_COMMANDS, print_help
from choreoai_cli.ui.prompt import budget_short, history_path, make_prompt_fn
from choreoai_cli.ui.theme import (
    ASCII_GLYPHS,
    GUTTER,
    SAND,
    TAUPE,
    TERRACOTTA,
    TERRACOTTA_DEEP,
    Glyphs,
    configure_stdio_utf8,
    glyphs,
    gutter_pad,
    init_output,
    make_console,
    stream_supports_unicode,
    unicode_output_ok,
)
from choreoai_cli.ui.toolcards import (
    LiveEventSubscriber,
    ToolArgTracker,
    instrument_tools_for_ui,
    preview_tool_result,
    summarize_tool_args,
)

__all__ = [
    "ASCII_GLYPHS",
    "GUTTER",
    "HELP_TEXT",
    "SAND",
    "SLASH_COMMANDS",
    "TAUPE",
    "TERRACOTTA",
    "TERRACOTTA_DEEP",
    "Glyphs",
    "LiveEventSubscriber",
    "ToolArgTracker",
    "budget_short",
    "configure_stdio_utf8",
    "glyphs",
    "gutter_pad",
    "history_path",
    "init_output",
    "instrument_tools_for_ui",
    "looks_like_code",
    "make_console",
    "make_prompt_fn",
    "model_label",
    "preview_tool_result",
    "print_api_key_note",
    "print_banner",
    "print_help",
    "print_result",
    "render_answer_body",
    "short_cwd",
    "stream_supports_unicode",
    "summarize_tool_args",
    "unicode_output_ok",
]
