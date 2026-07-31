"""Filesystem and shell tools for the coding agent (langchain-core BaseTool)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field


class ReadFileInput(BaseModel):
    path: str = Field(description="Path to the file to read (relative or absolute).")


class WriteFileInput(BaseModel):
    path: str = Field(description="Path to the file to write (relative or absolute).")
    content: str = Field(description="Full content to write to the file.")


class ListDirInput(BaseModel):
    path: str = Field(
        default=".",
        description="Directory path to list (relative or absolute). Defaults to cwd.",
    )


class RunShellInput(BaseModel):
    command: str = Field(description="Shell command to execute in the working directory.")


def _resolve(path: str, cwd: Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = cwd / p
    return p.resolve()


def make_read_file(cwd: Path | None = None) -> BaseTool:
    """Create a read_file tool rooted at ``cwd`` (default: process cwd)."""
    root = (cwd or Path.cwd()).resolve()

    def _read(path: str) -> str:
        target = _resolve(path, root)
        if not target.exists():
            return f"error: file not found: {path}"
        if not target.is_file():
            return f"error: not a file: {path}"
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"error: could not read {path}: {exc}"

    return StructuredTool.from_function(
        func=_read,
        name="read_file",
        description="Read the full text contents of a file at the given path.",
        args_schema=ReadFileInput,
    )


def make_write_file(cwd: Path | None = None) -> BaseTool:
    """Create a write_file tool rooted at ``cwd``."""
    root = (cwd or Path.cwd()).resolve()

    def _write(path: str, content: str) -> str:
        target = _resolve(path, root)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"wrote {len(content)} characters to {path}"
        except OSError as exc:
            return f"error: could not write {path}: {exc}"

    return StructuredTool.from_function(
        func=_write,
        name="write_file",
        description="Write text content to a file (creates parent directories).",
        args_schema=WriteFileInput,
    )


def make_list_dir(cwd: Path | None = None) -> BaseTool:
    """Create a list_dir tool rooted at ``cwd``."""
    root = (cwd or Path.cwd()).resolve()

    def _list(path: str = ".") -> str:
        target = _resolve(path, root)
        if not target.exists():
            return f"error: directory not found: {path}"
        if not target.is_dir():
            return f"error: not a directory: {path}"
        try:
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines: list[str] = []
            for entry in entries:
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{entry.name}{suffix}")
            return "\n".join(lines) if lines else "(empty)"
        except OSError as exc:
            return f"error: could not list {path}: {exc}"

    return StructuredTool.from_function(
        func=_list,
        name="list_dir",
        description="List files and subdirectories in a directory.",
        args_schema=ListDirInput,
    )


def make_run_shell(
    cwd: Path | None = None,
    *,
    auto: bool = False,
    confirm: Callable[[str], bool] | None = None,
) -> BaseTool:
    """Create a run_shell tool.

    By default, prompts for confirmation before executing (Claude-Code-style
    approval). Pass ``auto=True`` or a custom ``confirm`` callable to change
    that behavior.
    """
    root = (cwd or Path.cwd()).resolve()

    def _default_confirm(command: str) -> bool:
        try:
            answer = input(f"Allow shell command? [y/N]\n  $ {command}\n> ").strip().lower()
        except EOFError:
            return False
        return answer in ("y", "yes")

    conf = confirm if confirm is not None else _default_confirm

    def _run(command: str) -> str:
        if not auto:
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

    return StructuredTool.from_function(
        func=_run,
        name="run_shell",
        description=(
            "Run a shell command in the working directory. "
            "Requires user confirmation unless --auto is set."
        ),
        args_schema=RunShellInput,
    )


def default_tools(
    cwd: Path | None = None,
    *,
    auto: bool = False,
    confirm: Callable[[str], bool] | None = None,
) -> list[BaseTool]:
    """Return the standard coding-agent tool set for ``cwd``."""
    return [
        make_read_file(cwd),
        make_write_file(cwd),
        make_list_dir(cwd),
        make_run_shell(cwd, auto=auto, confirm=confirm),
    ]
