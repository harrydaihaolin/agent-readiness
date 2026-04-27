"""Docker-enforced sandbox for executing code from the target repo.

Per SANDBOX.md, *any* check that runs target-repo code goes through this
module. There is no host-execution fallback in v0.

This module defines the interface and types. The Docker plumbing
(`DockerSandbox.run`, `_pull_image`, etc.) is filled in during v0.2.
Static checks should not import this module — it's only loaded when
`--run` is enabled.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Phase(str, Enum):
    """Two-phase execution: setup (network on) then test (network off)."""
    SETUP = "setup"
    TEST = "test"


@dataclass
class SandboxRun:
    """Outcome of a single command executed inside a sandbox container."""
    phase: Phase
    command: list[str]
    exit_code: int
    duration_s: float
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    oom_killed: bool = False
    image: str = ""

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.oom_killed


@dataclass
class SandboxConfig:
    """Per-scan sandbox configuration. Sensible defaults for v0; overridable
    via CLI flags and `.agent-readiness.toml`."""
    image: str | None = None              # None = pick by ecosystem
    timeout_s: int = 300                  # wall-clock per phase
    memory: str = "2g"
    cpus: float = 2.0
    pids_limit: int = 512
    network_for_setup: bool = True        # setup needs deps
    network_for_test: bool = False        # tests run offline by default
    extra_env_allowlist: list[str] = field(default_factory=list)


class SandboxUnavailableError(RuntimeError):
    """Raised when --run is requested but Docker isn't usable.

    Carries an exit code (always 2) and a user-facing message; the CLI
    prints the message and exits with that code. Never silently fall
    back to host execution.
    """
    exit_code: int = 2

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def preflight() -> None:
    """Verify Docker is installed and the daemon is reachable.

    Called once before any sandboxed work runs. Raises
    SandboxUnavailableError with a user-facing message if Docker is not
    usable. No silent fallback — that's a hard rule from SANDBOX.md.
    """
    if shutil.which("docker") is None:
        raise SandboxUnavailableError(
            "Docker is required for `--run`. "
            "Install: https://docs.docker.com/get-docker/"
        )
    result = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if result.returncode != 0:
        raise SandboxUnavailableError(
            "Docker is installed but the daemon isn't reachable. "
            "Start Docker Desktop, or run `systemctl start docker` on Linux."
        )


class DockerSandbox:
    """Run commands inside ephemeral Docker containers per SANDBOX.md.

    v0.2 work — interface stub only.
    """

    def __init__(self, repo_path: Path, config: SandboxConfig) -> None:
        self.repo_path = repo_path.resolve()
        self.config = config

    def run(self, phase: Phase, command: list[str]) -> SandboxRun:
        """Run *command* inside the configured container for *phase*.

        Not yet implemented. v0.2 will:
          1. Resolve the image (config.image or ecosystem default).
          2. Pull if needed (with a streaming progress indicator).
          3. `docker run --rm --read-only --tmpfs /tmp ...` with mounts,
             memory/cpu/pids limits, and `--network=none` when
             `phase == TEST` (unless overridden in config).
          4. Enforce wall-clock timeout via subprocess timeout + a
             follow-up `docker kill` if the container outlives it.
          5. Detect OOM via `docker inspect` (`State.OOMKilled`).
          6. Return a SandboxRun with output tails.
        """
        raise NotImplementedError("DockerSandbox.run lands in v0.2")
