"""Filesystem tools: read_file, write_file, list_dir."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from choreoai_cli.tools.base import build_tool


class PathJailError(ValueError):
    """Raised when a path resolves outside the session root."""


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


def resolve_under_root(path: str, root: Path) -> Path:
    """Resolve ``path`` and reject anything that escapes ``root``.

    Relative paths are joined to ``root``. Absolute paths are allowed only when
    they still resolve under ``root``. ``../`` traversal out of the root raises
    ``PathJailError``.
    """
    root_resolved = root.resolve()
    p = Path(path)
    if not p.is_absolute():
        p = root_resolved / p
    target = p.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise PathJailError(
            f"path escapes session root: {path!r} -> {target} (root={root_resolved})"
        ) from exc
    return target


# Back-compat private alias used by tests.
_resolve_under_root = resolve_under_root


def make_read_file(cwd: Path | None = None) -> BaseTool:
    """Create a read_file tool rooted at ``cwd`` (default: process cwd)."""
    root = (cwd or Path.cwd()).resolve()

    def _read(path: str) -> str:
        try:
            target = resolve_under_root(path, root)
        except PathJailError as exc:
            return f"error: {exc}"
        if not target.exists():
            return f"error: file not found: {path}"
        if not target.is_file():
            return f"error: not a file: {path}"
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"error: could not read {path}: {exc}"

    return build_tool(
        name="read_file",
        description="Read the full text contents of a file at the given path.",
        func=_read,
        args_schema=ReadFileInput,
        is_read_only=True,
        is_concurrency_safe=True,
        activity_description=lambda d: f"Reading {d.get('path', '') or 'file'}",
    )


def make_write_file(cwd: Path | None = None) -> BaseTool:
    """Create a write_file tool rooted at ``cwd``."""
    root = (cwd or Path.cwd()).resolve()

    def _write(path: str, content: str) -> str:
        try:
            target = resolve_under_root(path, root)
        except PathJailError as exc:
            return f"error: {exc}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"wrote {len(content)} characters to {path}"
        except OSError as exc:
            return f"error: could not write {path}: {exc}"

    return build_tool(
        name="write_file",
        description="Write text content to a file (creates parent directories).",
        func=_write,
        args_schema=WriteFileInput,
        is_read_only=False,
        is_destructive=False,
        is_concurrency_safe=False,
        activity_description=lambda d: f"Writing {d.get('path', '') or 'file'}",
    )


def make_list_dir(cwd: Path | None = None) -> BaseTool:
    """Create a list_dir tool rooted at ``cwd``."""
    root = (cwd or Path.cwd()).resolve()

    def _list(path: str = ".") -> str:
        try:
            target = resolve_under_root(path, root)
        except PathJailError as exc:
            return f"error: {exc}"
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

    return build_tool(
        name="list_dir",
        description="List files and subdirectories in a directory.",
        func=_list,
        args_schema=ListDirInput,
        is_read_only=True,
        is_concurrency_safe=True,
        activity_description=lambda d: f"Listing {d.get('path', '.') or '.'}",
    )
