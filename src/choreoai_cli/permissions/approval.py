"""Shell approval policy built on PermissionContext."""

from __future__ import annotations

from typing import Callable

from choreoai_cli.permissions.context import (
    PermissionBehavior,
    PermissionContext,
    PermissionMode,
)


class ShellApprovalPolicy:
    """Session-scoped shell approval: y/N, always-allow, and deny patterns.

    Prompt answers (case-insensitive):
      - y / yes     — allow this command once
      - n / no / '' — deny this command once
      - a / always  — allow all shell commands for the rest of the session
      - deny <pat>  — add a deny substring pattern and reject this command
      - d <pat>     — same as deny <pat>
    """

    def __init__(
        self,
        input_fn: Callable[[str], str] | None = None,
        *,
        context: PermissionContext | None = None,
    ) -> None:
        self.context = context if context is not None else PermissionContext()
        self._input = input_fn if input_fn is not None else input
        # Mirror legacy attributes used by tests / tools.
        self.always_allow = self.context.always_allow_shell
        self.deny_patterns = self.context.deny_patterns

    def reset(self) -> None:
        """Clear session always-allow and deny patterns (e.g. on /reset)."""
        self.context.reset_session()
        self.always_allow = False
        # deny_patterns is the same list object on context; already cleared.
        self.deny_patterns = self.context.deny_patterns

    def matches_deny(self, command: str) -> str | None:
        """Return the first matching deny pattern, or None."""
        for pattern in self.context.deny_patterns:
            if pattern and pattern in command:
                return pattern
        return None

    def __call__(self, command: str) -> bool:
        denied = self.matches_deny(command)
        if denied is not None:
            return False

        # Sync legacy flag → context (tests may set policy.always_allow).
        if self.always_allow:
            self.context.always_allow_shell = True

        decision = self.context.check(
            "run_shell",
            is_destructive=True,
            input_data={"command": command},
        )
        if decision.behavior == PermissionBehavior.ALLOW:
            return True
        if decision.behavior == PermissionBehavior.DENY:
            return False

        # ASK — interactive prompt
        if self.context.mode in (PermissionMode.AUTO, PermissionMode.BYPASS):
            return True

        try:
            answer = self._input(
                "Allow shell command? [y/N/always/deny <pattern>]\n"
                f"  $ {command}\n> "
            ).strip()
        except EOFError:
            return False

        lower = answer.lower()
        if lower in ("y", "yes"):
            return True
        if lower in ("a", "always"):
            self.always_allow = True
            self.context.always_allow_shell = True
            return True
        if lower.startswith("deny ") or lower.startswith("d "):
            parts = answer.split(None, 1)
            if len(parts) == 2 and parts[1].strip():
                self.context.deny_patterns.append(parts[1].strip())
            return False
        if lower == "deny":
            # Deny this exact command string for the rest of the session.
            self.context.deny_patterns.append(command)
            return False
        return False
