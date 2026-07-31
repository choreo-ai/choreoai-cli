"""Turn footer stats and final answer print."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.padding import Padding
from rich.rule import Rule
from rich.text import Text

from choreoai_cli.ui.answer import render_answer_body
from choreoai_cli.ui.theme import (
    GUTTER,
    SAND,
    TAUPE,
    TERRACOTTA,
    estimate_cost_usd,
    format_cost,
    glyphs,
    gutter_pad,
)


def print_result(
    console: Console,
    harness: Any,
    result: Any,
    *,
    live: Any | None = None,
    elapsed_s: float | None = None,
) -> None:
    """Render the assistant answer plus a dim turn footer (tokens / budget / time)."""
    text = result.output if result.output is not None else "(no output)"
    if not isinstance(text, str):
        text = str(text)

    g = glyphs()
    header = Text()
    header.append(g.bullet, style=f"bold {TERRACOTTA}")
    header.append(" ", style="")
    header.append("Answer", style=f"bold {SAND}")
    console.print()
    console.print(gutter_pad(header))
    console.print(Padding(render_answer_body(text), (0, 0, 0, GUTTER + 2)))
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

    console.print(Rule(style=f"dim {TAUPE}"))

    parts: list[str] = []
    sep = f" {g.middot} "
    if in_tok or out_tok:
        parts.append(f"tokens {in_tok}↑ {out_tok}↓")
        parts.append(f"est {format_cost(estimate_cost_usd(in_tok, out_tok))}")
    if tools_n or llm_n:
        parts.append(f"tools={tools_n} llm={llm_n}")
    if budget_parts:
        parts.append("budget " + sep.join(budget_parts))
    if elapsed_s is not None:
        if elapsed_s < 10:
            parts.append(f"{elapsed_s:.1f}s")
        else:
            parts.append(f"{elapsed_s:.0f}s")

    footer = Text(sep.join(parts), style=f"dim {TAUPE}")
    console.print(gutter_pad(footer))
    console.print(
        gutter_pad(
            Text(f"trace: {harness.trace_summary()}", style=f"dim {TAUPE}")
        )
    )
    console.print()
