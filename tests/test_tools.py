"""Offline unit tests for coding tools."""

from __future__ import annotations

from pathlib import Path

from choreo_cli.tools import (
    default_tools,
    make_list_dir,
    make_read_file,
    make_run_shell,
    make_write_file,
)


def test_read_file(tmp_project: Path) -> None:
    tool = make_read_file(tmp_project)
    out = tool.invoke({"path": "hello.txt"})
    assert "hello world" in out


def test_read_missing(tmp_project: Path) -> None:
    tool = make_read_file(tmp_project)
    out = tool.invoke({"path": "missing.txt"})
    assert "error" in out.lower()


def test_write_and_read(tmp_project: Path) -> None:
    write = make_write_file(tmp_project)
    read = make_read_file(tmp_project)
    msg = write.invoke({"path": "out/note.txt", "content": "saved"})
    assert "wrote" in msg
    assert read.invoke({"path": "out/note.txt"}) == "saved"


def test_list_dir(tmp_project: Path) -> None:
    tool = make_list_dir(tmp_project)
    out = tool.invoke({"path": "."})
    assert "hello.txt" in out
    assert "src/" in out


def test_run_shell_requires_confirm(tmp_project: Path) -> None:
    rejected = make_run_shell(tmp_project, auto=False, confirm=lambda _c: False)
    out = rejected.invoke({"command": "echo hi"})
    assert "rejected" in out.lower()


def test_run_shell_auto(tmp_project: Path) -> None:
    tool = make_run_shell(tmp_project, auto=True)
    out = tool.invoke({"command": "echo hello-choreo"})
    assert "exit_code=0" in out
    assert "hello-choreo" in out


def test_default_tools_names(tmp_project: Path) -> None:
    tools = default_tools(tmp_project, auto=True)
    names = {t.name for t in tools}
    assert names == {"read_file", "write_file", "list_dir", "run_shell"}
