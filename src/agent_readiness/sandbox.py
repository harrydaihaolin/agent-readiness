"""Docker-enforced sandbox for executing code from the target repo.

Per SANDBOX.md, *any* check that runs target-repo code goes through this
module. There is no host-execution fallback in v0.

This module defines the interface and types. The Docker plumbing
(`DockerSandbox.run`, image resolution, devcontainer build, etc.) is
filled in during v0.2. Static checks should not import this module —
it's only loaded when `--run` is enabled.
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


class ImageSource(str, Enum):
    """How the sandbox image was determined for this scan.

    Affects user messaging ("using your devcontainer..." vs "using
    Python ecosystem default...") and which findings the resolver
    emits alongside the run.
    """
    DEVCONTAINER_IMAGE = "devcontainer_image"        # devcontainer.json image:
    DEVCONTAINER_BUILT = "devcontainer_built"        # built from dockerFile:
    ECOSYSTEM_DEFAULT = "ecosystem_default"          # pinned-digest per language
    UNIVERSAL_FALLBACK = "universal_fallback"        # polyglot / unknown
    USER_OVERRIDE = "user_override"                  # --image flag or config


@dataclass
class ResolvedImage:
    """Result of image resolution; consumed by DockerSandbox.run."""
    reference: str                # docker image ref, e.g. python:3.12-slim@sha256:...
    source: ImageSource
    notes: list[str] = field(default_factory=list)  # surfaced to the user


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
    image: str | None = None              # None = resolve via devcontainer/ecosystem
    timeout_s: int = 300                  # wall-clock per phase
    build_timeout_s: int = 600            # devcontainer / docker build timeout
    memory: str = "2g"
    cpus: float = 2.0
    pids_limit: int = 512
    network_for_setup: bool = True        # setup needs deps
    network_for_test: bool = False        # tests run offline by default
    extra_env_allowlist: list[str] = field(default_factory=list)
    prefer_devcontainer: bool = True      # use devcontainer.json if present


class SandboxUnavailableError(RuntimeError):
    """Raised when --run is requested but Docker isn't usable, or the repo
    is detected as docker-native and we refuse to sandbox it.

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


def detect_docker_native(repo_path: Path) -> str | None:
    """Return a human-readable reason if this repo is docker-native, else None.

    Per SANDBOX.md, docker-native repos are hard-failed for `--run`.
    Detection is intentionally conservative — we'd rather refuse to
    score than score wrong.

    v0.2 will check:
      - devcontainer.json `dockerComposeFile`
      - root `docker-compose.yml` / `compose.yml` referenced from the
        detected test command
      - test command shells out to `docker run` / `docker build` /
        `docker compose`
    """
    raise NotImplementedError("detect_docker_native lands in v0.2")


def resolve_image(repo_path: Path, config: SandboxConfig) -> ResolvedImage:
    """Pick the image to run in.

    Priority (v0.2):
      1. `config.image` (user override) → ImageSource.USER_OVERRIDE
      2. devcontainer.json `image:` → DEVCONTAINER_IMAGE
      3. devcontainer.json `dockerFile:` (built) → DEVCONTAINER_BUILT
      4. ecosystem-default by manifest → ECOSYSTEM_DEFAULT
      5. universal fallback → UNIVERSAL_FALLBACK

    `dockerComposeFile` triggers docker-native detection upstream and
    never reaches this function.
    """
    raise NotImplementedError("resolve_image lands in v0.2")


class DockerSandbox:
    """Run commands inside ephemeral Docker containers per SANDBOX.md.

    v0.2 work — interface stub only.
    """

    def __init__(self, repo_path: Path, config: SandboxConfig,
                 image: ResolvedImage) -> None:
        self.repo_path = repo_path.resolve()
        self.config = config
        self.image = image

    def run(self, phase: Phase, command: list[str]) -> SandboxRun:
        """Run *command* inside the configured container for *phase*.

        Not yet implemented. v0.2 will:
          1. `docker run --rm --read-only --tmpfs /tmp ...` with mounts,
             memory/cpu/pids limits, and `--network=none` when
             `phase == TEST` (unless overridden in config).
          2. Enforce wall-clock timeout via subprocess timeout + a
             follow-up `docker kill` if the container outlives it.
          3. Detect OOM via `docker inspect` (`State.OOMKilled`).
          4. Return a SandboxRun with output tails.
        """
        raise NotImplementedError("DockerSandbox.run lands in v0.2")
