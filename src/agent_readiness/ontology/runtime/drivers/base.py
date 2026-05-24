from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DriverResult:
    success: bool
    stdout: str
    stderr: str
    command_run: str
    duration_ms: int


class DriverAuthError(RuntimeError):
    """Raised when a required API token environment variable is missing."""

    def __init__(self, env_var: str) -> None:
        super().__init__(f"Missing required environment variable: {env_var}")
        self.env_var = env_var


class DriverUnavailableError(RuntimeError):
    """Raised when subprocess execution is unavailable."""


class Driver(Protocol):
    def execute(
        self, command: str, args: dict, *, dry_run: bool = False
    ) -> DriverResult: ...
