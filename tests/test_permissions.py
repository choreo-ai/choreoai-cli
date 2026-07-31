"""Offline tests for the 3-tier permission context."""

from __future__ import annotations

from choreoai_cli.permissions import (
    PermissionBehavior,
    PermissionContext,
    PermissionMode,
    ShellApprovalPolicy,
)


def test_from_auto_flag() -> None:
    assert PermissionContext.from_auto(True).mode == PermissionMode.AUTO
    assert PermissionContext.from_auto(False).mode == PermissionMode.DEFAULT


def test_auto_mode_allows_shell() -> None:
    ctx = PermissionContext(mode=PermissionMode.AUTO)
    r = ctx.check("run_shell", is_destructive=True)
    assert r.behavior == PermissionBehavior.ALLOW


def test_default_mode_asks_shell() -> None:
    ctx = PermissionContext(mode=PermissionMode.DEFAULT)
    r = ctx.check("run_shell", is_destructive=True)
    assert r.behavior == PermissionBehavior.ASK


def test_default_allows_readonly() -> None:
    ctx = PermissionContext(mode=PermissionMode.DEFAULT)
    r = ctx.check("read_file", is_read_only=True)
    assert r.behavior == PermissionBehavior.ALLOW


def test_plan_mode_readonly_vs_write() -> None:
    ctx = PermissionContext(mode=PermissionMode.PLAN)
    assert ctx.check("list_dir", is_read_only=True).behavior == PermissionBehavior.ALLOW
    assert ctx.check("run_shell", is_destructive=True).behavior == PermissionBehavior.ASK


def test_deny_tool_rule() -> None:
    ctx = PermissionContext(always_deny_tools={"run_shell"})
    r = ctx.check("run_shell", is_destructive=True)
    assert r.behavior == PermissionBehavior.DENY


def test_shell_policy_always_allow() -> None:
    answers = iter(["always"])
    policy = ShellApprovalPolicy(input_fn=lambda _p: next(answers))
    assert policy("echo once") is True
    assert policy.always_allow is True
    # Second call must not prompt.
    assert policy("echo twice") is True
