"""Tool registry: assemble the coding-agent tool pool."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from langchain_core.tools import BaseTool

from choreoai_cli.permissions.approval import ShellApprovalPolicy
from choreoai_cli.permissions.context import PermissionContext
from choreoai_cli.tools.base import (
    ToolSafety,
    activity_description,
    build_tool,
    copy_safety,
    get_tool_safety,
    is_concurrency_safe,
    is_destructive,
    is_read_only,
)
from choreoai_cli.tools.files import (
    PathJailError,
    _resolve_under_root,
    make_list_dir,
    make_read_file,
    make_write_file,
    resolve_under_root,
)
from choreoai_cli.tools.shell import make_run_shell

__all__ = [
    "PathJailError",
    "ShellApprovalPolicy",
    "ToolSafety",
    "_resolve_under_root",
    "activity_description",
    "build_tool",
    "copy_safety",
    "default_tools",
    "get_default_tools",
    "get_tool_safety",
    "is_concurrency_safe",
    "is_destructive",
    "is_read_only",
    "make_list_dir",
    "make_read_file",
    "make_run_shell",
    "make_write_file",
    "resolve_under_root",
]


def get_default_tools(
    cwd: Path | None = None,
    *,
    auto: bool = False,
    confirm: Callable[[str], bool] | None = None,
    permission_context: PermissionContext | None = None,
) -> list[BaseTool]:
    """Assemble the standard coding-agent tool pool for ``cwd``."""
    ctx = permission_context
    if ctx is None:
        ctx = PermissionContext.from_auto(auto)
    return [
        make_read_file(cwd),
        make_write_file(cwd),
        make_list_dir(cwd),
        make_run_shell(
            cwd,
            auto=auto,
            confirm=confirm,
            permission_context=ctx,
        ),
    ]


# Back-compat alias.
default_tools = get_default_tools
