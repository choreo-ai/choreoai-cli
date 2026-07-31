"""CLI configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from choreoai_cli.permissions.context import PermissionMode


@dataclass
class CliConfig:
    """Runtime configuration for a choreoai-cli session."""

    cwd: Path
    auto: bool = False
    max_steps: int = 10
    step_budget: float = 20.0
    command: str | None = None

    @property
    def permission_mode(self) -> PermissionMode:
        """Map ``--auto`` to permission mode (auto/bypass shell prompts)."""
        return PermissionMode.AUTO if self.auto else PermissionMode.DEFAULT
