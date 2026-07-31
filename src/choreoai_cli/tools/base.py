"""Tool base helpers: build_tool() factory with fail-closed safety flags.

Adapted from Claude Code's Tool / buildTool / TOOL_DEFAULTS pattern.
Safety defaults are fail-closed: not read-only, not destructive, not
concurrency-safe until a tool declares otherwise.

Safety metadata lives in tool.metadata (pydantic field) plus an id-keyed
side table for callables — StructuredTool rejects free attributes and is
unhashable (no WeakKeyDictionary).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

# Fail-closed defaults (Claude Code TOOL_DEFAULTS).
_DEFAULT_IS_READ_ONLY = False
_DEFAULT_IS_DESTRUCTIVE = False
_DEFAULT_IS_CONCURRENCY_SAFE = False

# id(tool) → ToolSafety (StructuredTool is unhashable; process-lifetime OK).
_SAFETY_BY_ID: dict[int, "ToolSafety"] = {}


@dataclass
class ToolSafety:
    """Safety metadata attached to every built tool."""

    is_read_only: bool = _DEFAULT_IS_READ_ONLY
    is_destructive: bool = _DEFAULT_IS_DESTRUCTIVE
    is_concurrency_safe: bool = _DEFAULT_IS_CONCURRENCY_SAFE
    activity_description: Callable[[dict[str, Any]], str] | None = None


def _attach_safety(tool: BaseTool, safety: ToolSafety) -> BaseTool:
    """Stamp safety flags into metadata + side table."""
    _SAFETY_BY_ID[id(tool)] = safety
    try:
        meta = dict(tool.metadata or {})
        meta["is_read_only"] = safety.is_read_only
        meta["is_destructive"] = safety.is_destructive
        meta["is_concurrency_safe"] = safety.is_concurrency_safe
        tool.metadata = meta
    except Exception:
        pass
    return tool


def get_tool_safety(tool: BaseTool) -> ToolSafety:
    """Read safety metadata from a tool (fail-closed defaults if missing)."""
    safety = _SAFETY_BY_ID.get(id(tool))
    if isinstance(safety, ToolSafety):
        return safety
    meta = getattr(tool, "metadata", None) or {}
    return ToolSafety(
        is_read_only=bool(meta.get("is_read_only", _DEFAULT_IS_READ_ONLY)),
        is_destructive=bool(meta.get("is_destructive", _DEFAULT_IS_DESTRUCTIVE)),
        is_concurrency_safe=bool(
            meta.get("is_concurrency_safe", _DEFAULT_IS_CONCURRENCY_SAFE)
        ),
    )


def is_read_only(tool: BaseTool, input_data: dict[str, Any] | None = None) -> bool:
    return get_tool_safety(tool).is_read_only


def is_destructive(tool: BaseTool, input_data: dict[str, Any] | None = None) -> bool:
    return get_tool_safety(tool).is_destructive


def is_concurrency_safe(
    tool: BaseTool, input_data: dict[str, Any] | None = None
) -> bool:
    return get_tool_safety(tool).is_concurrency_safe


def activity_description(
    tool: BaseTool, input_data: dict[str, Any] | None = None
) -> str:
    """Human-facing activity string for spinner / tool-card text."""
    safety = get_tool_safety(tool)
    data = input_data or {}
    if safety.activity_description is not None:
        try:
            return str(safety.activity_description(data))
        except Exception:
            pass
    return tool.name


def build_tool(
    *,
    name: str,
    description: str,
    func: Callable[..., Any],
    args_schema: type[BaseModel],
    is_read_only: bool = _DEFAULT_IS_READ_ONLY,
    is_destructive: bool = _DEFAULT_IS_DESTRUCTIVE,
    is_concurrency_safe: bool = _DEFAULT_IS_CONCURRENCY_SAFE,
    activity_description: Callable[[dict[str, Any]], str] | None = None,
) -> BaseTool:
    """Factory mirroring Claude Code ``buildTool()`` with fail-closed defaults.

    Required: name, description, func, args_schema.
    Optional safety flags default to the fail-closed TOOL_DEFAULTS.
    """
    tool = StructuredTool.from_function(
        func=func,
        name=name,
        description=description,
        args_schema=args_schema,
    )
    return _attach_safety(
        tool,
        ToolSafety(
            is_read_only=is_read_only,
            is_destructive=is_destructive,
            is_concurrency_safe=is_concurrency_safe,
            activity_description=activity_description,
        ),
    )


def copy_safety(src: BaseTool, dest: BaseTool) -> BaseTool:
    """Copy safety metadata when wrapping a tool (e.g. UI instrumentation)."""
    safety = _SAFETY_BY_ID.get(id(src))
    if safety is not None:
        _attach_safety(dest, safety)
    else:
        # Fall back to flags stored in metadata.
        _attach_safety(dest, get_tool_safety(src))
    return dest
