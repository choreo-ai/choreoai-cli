"""Offline unit tests for coding tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from choreo_cli.tools import (
    PathJailError,
    ShellApprovalPolicy,
    _resolve_under_root,
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


def test_path_jail_rejects_parent_traversal(tmp_project: Path) -> None:
    """../ that escapes the session root must be rejected."""
    outside = tmp_project.parent / "secret_outside.txt"
    outside.write_text("leaked", encoding="utf-8")
    try:
        read = make_read_file(tmp_project)
        out = read.invoke({"path": "../secret_outside.txt"})
        assert "error" in out.lower()
        assert "escapes" in out.lower() or "session root" in out.lower()

        write = make_write_file(tmp_project)
        wout = write.invoke({"path": "../pwned.txt", "content": "nope"})
        assert "error" in wout.lower()

        listed = make_list_dir(tmp_project)
        lout = listed.invoke({"path": ".."})
        assert "error" in lout.lower()
    finally:
        if outside.exists():
            outside.unlink()


def test_path_jail_rejects_absolute_outside_root(tmp_project: Path, tmp_path_factory) -> None:
    other = tmp_path_factory.mktemp("outside")
    secret = other / "secret.txt"
    secret.write_text("top-secret", encoding="utf-8")

    read = make_read_file(tmp_project)
    out = read.invoke({"path": str(secret)})
    assert "error" in out.lower()
    assert "escapes" in out.lower() or "session root" in out.lower()


def test_path_jail_allows_absolute_inside_root(tmp_project: Path) -> None:
    target = (tmp_project / "hello.txt").resolve()
    read = make_read_file(tmp_project)
    out = read.invoke({"path": str(target)})
    assert "hello world" in out


def test_resolve_under_root_raises() -> None:
    root = Path.cwd().resolve()
    with pytest.raises(PathJailError):
        _resolve_under_root("../../../etc/passwd", root)


def test_run_shell_requires_confirm(tmp_project: Path) -> None:
    rejected = make_run_shell(tmp_project, auto=False, confirm=lambda _c: False)
    out = rejected.invoke({"command": "echo hi"})
    assert "rejected" in out.lower()


def test_run_shell_auto(tmp_project: Path) -> None:
    tool = make_run_shell(tmp_project, auto=True)
    out = tool.invoke({"command": "echo hello-choreo"})
    assert "exit_code=0" in out
    assert "hello-choreo" in out


def test_run_shell_always_allow_session(tmp_project: Path) -> None:
    answers = iter(["always"])
    policy = ShellApprovalPolicy(input_fn=lambda _prompt: next(answers))
    tool = make_run_shell(tmp_project, auto=False, confirm=policy)

    first = tool.invoke({"command": "echo first-always"})
    assert "exit_code=0" in first
    assert policy.always_allow is True

    # Second call must not prompt (would StopIteration if it did).
    second = tool.invoke({"command": "echo second-always"})
    assert "exit_code=0" in second
    assert "second-always" in second


def test_run_shell_deny_pattern_session(tmp_project: Path) -> None:
    answers = iter(["deny rm "])
    policy = ShellApprovalPolicy(input_fn=lambda _prompt: next(answers))
    tool = make_run_shell(tmp_project, auto=False, confirm=policy)

    denied = tool.invoke({"command": "rm -rf /tmp/x"})
    assert "rejected" in denied.lower()
    assert "deny pattern" in denied.lower() or "rejected by user" in denied.lower()
    # "deny rm " is parsed to pattern "rm" (whitespace-split).
    assert any("rm" in p for p in policy.deny_patterns)

    # Matching command is blocked without prompting again.
    again = tool.invoke({"command": "rm something"})
    assert "rejected" in again.lower()
    assert "deny pattern" in again.lower()


def test_run_shell_auto_bypasses_policy(tmp_project: Path) -> None:
    policy = ShellApprovalPolicy(input_fn=lambda _p: (_ for _ in ()).throw(AssertionError("no prompt")))
    policy.deny_patterns.append("echo")
    tool = make_run_shell(tmp_project, auto=True, confirm=policy)
    out = tool.invoke({"command": "echo bypass"})
    assert "exit_code=0" in out


def test_default_tools_names(tmp_project: Path) -> None:
    tools = default_tools(tmp_project, auto=True)
    names = {t.name for t in tools}
    assert names == {"read_file", "write_file", "list_dir", "run_shell"}
