"""Shell tool: run_shell with permission-aware approval."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from choreoai_cli.permissions.approval import ShellApprovalPolicy
from choreoai_cli.permissions.context import PermissionContext, PermissionMode
from choreoai_cli.tools.base import build_tool


class RunShellInput(BaseModel):
    command: str = Field(description="Shell command to execute in the working directory.")


def make_run_shell(
    cwd: Path | None = None,
    *,
    auto: bool = False,
    confirm: Callable[[str], bool] | None = None,
    permission_context: PermissionContext | None = None,
) -> BaseTool:
    """Create a run_shell tool.

    By default, prompts for confirmation before executing (Claude-Code-style
    approval with session always-allow and deny patterns). Pass ``auto=True``
    or a custom ``confirm`` callable to change that behavior.

    Permission routing: ``PermissionContext`` mode auto/bypass skips prompts;
    deny patterns and interactive ask still apply in default mode.
    """
    root = (cwd or Path.cwd()).resolve()

    if permission_context is None:
        permission_context = PermissionContext.from_auto(auto)
    elif auto and permission_context.mode == PermissionMode.DEFAULT:
        permission_context.mode = PermissionMode.AUTO

    if confirm is None:
        conf: Callable[[str], bool] = ShellApprovalPolicy(context=permission_context)
    else:
        conf = confirm

    def _run(command: str) -> str:
        # Auto / bypass: skip confirm entirely (legacy --auto behaviour).
        if permission_context.mode in (PermissionMode.AUTO, PermissionMode.BYPASS):
            pass
        else:
            if conf is not None and hasattr(conf, "matches_deny"):
                pattern = conf.matches_deny(command)  # type: ignore[attr-defined]
                if pattern is not None:
                    return (
                        f"error: shell command rejected by deny pattern "
                        f"({pattern!r})"
                    )
            if not conf(command):
                return "error: shell command rejected by user"
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=120,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            return "error: command timed out after 120s"
        except OSError as exc:
            return f"error: failed to run command: {exc}"

        parts: list[str] = [f"exit_code={completed.returncode}"]
        if completed.stdout:
            parts.append(f"stdout:\n{completed.stdout.rstrip()}")
        if completed.stderr:
            parts.append(f"stderr:\n{completed.stderr.rstrip()}")
        return "\n".join(parts)

    def _activity(d: dict) -> str:
        cmd = str(d.get("command", "") or "")
        if len(cmd) > 48:
            cmd = cmd[:47] + "…"
        return f"Running {cmd}" if cmd else "Running shell"

    return build_tool(
        name="run_shell",
        description=(
            "Run a shell command in the working directory. "
            "Requires user confirmation unless --auto is set."
        ),
        func=_run,
        args_schema=RunShellInput,
        is_read_only=False,
        is_destructive=True,
        is_concurrency_safe=False,
        activity_description=_activity,
    )
