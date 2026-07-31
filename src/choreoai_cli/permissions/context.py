"""3-tier permission context (allow / deny / ask) with modes.

Adapted from Claude Code's permission model — pragmatic subset for a small CLI:
modes ``default``, ``auto``, ``plan``, ``bypass``; no MDM / classifier layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PermissionMode(str, Enum):
    """Session permission mode.

    - ``default`` — ask before shell / destructive tools
    - ``auto``    — auto-allow tools (maps from ``--auto``)
    - ``plan``    — read-only tools allowed; writes/shell ask
    - ``bypass``  — same as auto for this CLI (no enterprise gates)
    """

    DEFAULT = "default"
    AUTO = "auto"
    PLAN = "plan"
    BYPASS = "bypass"


class PermissionBehavior(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class PermissionResult:
    """Outcome of a permission check."""

    behavior: PermissionBehavior
    reason: str = ""
    message: str = ""


@dataclass
class PermissionContext:
    """Allow / deny / ask rules plus mode for tool permission decisions.

    Fail-closed for shell and destructive tools in ``default`` mode.
    """

    mode: PermissionMode = PermissionMode.DEFAULT
    always_allow_tools: set[str] = field(default_factory=set)
    always_deny_tools: set[str] = field(default_factory=set)
    always_ask_tools: set[str] = field(default_factory=set)
    # Session deny substring patterns for shell commands.
    deny_patterns: list[str] = field(default_factory=list)
    always_allow_shell: bool = False

    @classmethod
    def from_auto(cls, auto: bool) -> PermissionContext:
        """Build context from the CLI ``--auto`` flag."""
        mode = PermissionMode.AUTO if auto else PermissionMode.DEFAULT
        return cls(mode=mode)

    def reset_session(self) -> None:
        """Clear session-scoped always-allow shell and deny patterns."""
        self.always_allow_shell = False
        self.deny_patterns.clear()

    def check(
        self,
        tool_name: str,
        *,
        is_read_only: bool = False,
        is_destructive: bool = False,
        input_data: dict[str, Any] | None = None,
    ) -> PermissionResult:
        """``checkPermissions``-style decision for a tool invocation.

        Order (simplified from Claude Code's pipeline):
        1. Full-tool deny rules
        2. Full-tool ask rules
        3. Mode-based bypass (auto / bypass)
        4. Full-tool allow rules
        5. Plan mode: read-only allow, else ask
        6. Default: read-only allow; shell/destructive ask
        """
        if tool_name in self.always_deny_tools:
            return PermissionResult(
                PermissionBehavior.DENY,
                reason="rule",
                message=f"tool {tool_name!r} is denied by rule",
            )

        if tool_name in self.always_ask_tools:
            return PermissionResult(
                PermissionBehavior.ASK,
                reason="rule",
                message=f"tool {tool_name!r} always requires approval",
            )

        # Mode-based auto-allow (maps --auto → auto/bypass).
        if self.mode in (PermissionMode.AUTO, PermissionMode.BYPASS):
            return PermissionResult(
                PermissionBehavior.ALLOW,
                reason="mode",
                message=f"mode={self.mode.value}",
            )

        if tool_name in self.always_allow_tools:
            return PermissionResult(
                PermissionBehavior.ALLOW,
                reason="rule",
                message=f"tool {tool_name!r} is always allowed",
            )

        if self.mode == PermissionMode.PLAN:
            if is_read_only:
                return PermissionResult(
                    PermissionBehavior.ALLOW,
                    reason="plan_readonly",
                    message="read-only tool allowed in plan mode",
                )
            return PermissionResult(
                PermissionBehavior.ASK,
                reason="plan_write",
                message="write/execute requires approval in plan mode",
            )

        # default mode
        if is_read_only and not is_destructive:
            return PermissionResult(
                PermissionBehavior.ALLOW,
                reason="readonly",
                message="read-only tool",
            )

        if tool_name == "run_shell" or is_destructive:
            if self.always_allow_shell and tool_name == "run_shell":
                return PermissionResult(
                    PermissionBehavior.ALLOW,
                    reason="session_always",
                    message="shell always-allow for session",
                )
            # Shell deny patterns checked by approval policy before execute.
            return PermissionResult(
                PermissionBehavior.ASK,
                reason="default",
                message="approval required",
            )

        # Non-destructive writes (e.g. write_file): allow in default for this CLI
        # (historical behaviour — only run_shell prompted).
        return PermissionResult(
            PermissionBehavior.ALLOW,
            reason="default_write",
            message="file write allowed",
        )
