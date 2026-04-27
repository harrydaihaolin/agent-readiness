"""Docker-enforced sandbox for executing code from the target repo.

Per SANDBOX.md, *any* check that runs target-repo code goes through this
module. There is no host-execution fallback in v0.

This module defines the interface and types. The Docker plumbing
(`DockerSandbox.run`, image resolution, devcontainer build, etc.) is
filled in during v0.2.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from uuid import uuid4


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


def _read_devcontainer_json(repo_path: Path) -> dict | None:
    """Parse devcontainer.json from .devcontainer/ or root."""
    candidates = [
        repo_path / ".devcontainer" / "devcontainer.json",
        repo_path / ".devcontainer.json",
    ]
    for p in candidates:
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    return None


def detect_docker_native(repo_path: Path) -> str | None:
    """Return a human-readable reason if this repo is docker-native, else None.

    Per SANDBOX.md, docker-native repos are hard-failed for `--run`.
    Detection is intentionally conservative — we'd rather refuse to
    score than score wrong.

    Checks:
      - devcontainer.json `dockerComposeFile`
      - root `docker-compose.yml` / `compose.yml`
      - Makefile test target that mentions docker
    """
    dc = _read_devcontainer_json(repo_path)
    if dc and "dockerComposeFile" in dc:
        return "devcontainer.json uses dockerComposeFile (docker-native repo)"

    for compose_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml"):
        if (repo_path / compose_name).is_file():
            makefile = repo_path / "Makefile"
            if makefile.is_file():
                try:
                    text = makefile.read_text(encoding="utf-8", errors="replace")
                    if "docker" in text.lower():
                        return (
                            f"Repo has {compose_name} and Makefile references docker — "
                            "likely a docker-native workflow"
                        )
                except OSError:
                    pass

    return None


def resolve_image(repo_path: Path, config: SandboxConfig) -> ResolvedImage:
    """Pick the image to run in.

    Priority:
      1. `config.image` (user override) → ImageSource.USER_OVERRIDE
      2. devcontainer.json `image:` → DEVCONTAINER_IMAGE
      3. devcontainer.json `build:` or `dockerFile:` → DEVCONTAINER_BUILT
      4. ecosystem-default by manifest → ECOSYSTEM_DEFAULT
      5. universal fallback → UNIVERSAL_FALLBACK
    """
    # 1. User override
    if config.image:
        return ResolvedImage(
            reference=config.image,
            source=ImageSource.USER_OVERRIDE,
            notes=["Using user-provided image override."],
        )

    # 2 & 3. devcontainer.json
    dc = _read_devcontainer_json(repo_path)
    if dc:
        if "image" in dc:
            return ResolvedImage(
                reference=dc["image"],
                source=ImageSource.DEVCONTAINER_IMAGE,
                notes=["Using image from devcontainer.json."],
            )
        if "build" in dc or "dockerFile" in dc:
            # Try devcontainer CLI first, else plain docker build
            if shutil.which("devcontainer"):
                notes = ["Building from devcontainer.json using devcontainer CLI."]
            else:
                notes = [
                    "devcontainer CLI not found; using plain docker build. "
                    "Install @devcontainers/cli for full support."
                ]
            # Determine build context
            docker_file = dc.get("dockerFile") or (
                dc.get("build", {}).get("dockerfile") if isinstance(dc.get("build"), dict) else None
            )
            if docker_file:
                dockerfile_path = repo_path / ".devcontainer" / docker_file
                if not dockerfile_path.is_file():
                    dockerfile_path = repo_path / docker_file
            else:
                dockerfile_path = repo_path / ".devcontainer" / "Dockerfile"

            image_tag = f"agent-readiness-devcontainer:{uuid4().hex[:8]}"
            return ResolvedImage(
                reference=image_tag,
                source=ImageSource.DEVCONTAINER_BUILT,
                notes=notes,
            )

    # 4. Ecosystem defaults (highest-priority manifest wins)
    ecosystem_defaults = [
        ("pyproject.toml", "python:3.12-slim"),
        ("setup.py", "python:3.12-slim"),
        ("package.json", "node:20-slim"),
        ("Cargo.toml", "rust:1.77-slim"),
        ("go.mod", "golang:1.22-alpine"),
        ("Gemfile", "ruby:3.3-slim"),
    ]
    for manifest, image in ecosystem_defaults:
        if (repo_path / manifest).is_file():
            return ResolvedImage(
                reference=image,
                source=ImageSource.ECOSYSTEM_DEFAULT,
                notes=[f"Using ecosystem default for {manifest}: {image}"],
            )

    # 5. Universal fallback
    return ResolvedImage(
        reference="ghcr.io/devcontainers/base:ubuntu",
        source=ImageSource.UNIVERSAL_FALLBACK,
        notes=["No manifest or devcontainer.json found; using universal fallback image."],
    )


class DockerSandbox:
    """Run commands inside ephemeral Docker containers per SANDBOX.md."""

    def __init__(self, repo_path: Path, config: SandboxConfig,
                 image: ResolvedImage) -> None:
        self.repo_path = repo_path.resolve()
        self.config = config
        self.image = image

    def run(self, phase: Phase, command: list[str]) -> SandboxRun:
        """Run *command* inside the configured container for *phase*.

        Uses a unique container name so concurrent runs don't collide.
        Enforces timeout via subprocess.TimeoutExpired + docker kill.
        Returns a SandboxRun with stdout/stderr tails (last 80 lines).
        """
        name = f"agent-readiness-{phase.value}-{uuid4().hex[:8]}"
        cmd = [
            "docker", "run", "--rm",
            "--name", name,
            "--read-only",
            "--tmpfs", "/tmp:size=256m",
            "--memory", self.config.memory,
            "--cpus", str(self.config.cpus),
            "--pids-limit", str(self.config.pids_limit),
            "--workdir", "/repo",
            "--mount", f"type=bind,source={self.repo_path},target=/repo,readonly",
            "--env", "CI=true",
        ]

        # Add network none for TEST phase when configured
        if phase is Phase.TEST and not self.config.network_for_test:
            cmd.append("--network=none")

        cmd.append(self.image.reference)
        cmd.extend(command)

        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_s,
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = -1
            stdout = ""
            stderr = f"Timed out after {self.config.timeout_s}s"
            # Kill the container by name
            subprocess.run(
                ["docker", "kill", name],
                capture_output=True, check=False,
            )
        duration_s = time.monotonic() - start

        # Check OOM via docker inspect (best-effort)
        oom_killed = False
        if not timed_out:
            inspect_result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.OOMKilled}}", name],
                capture_output=True, text=True, check=False,
            )
            oom_killed = inspect_result.stdout.strip().lower() == "true"

        def _tail(text: str, n: int = 80) -> str:
            lines = text.splitlines()
            return "\n".join(lines[-n:]) if len(lines) > n else text

        return SandboxRun(
            phase=phase,
            command=command,
            exit_code=exit_code,
            duration_s=round(duration_s, 2),
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            timed_out=timed_out,
            oom_killed=oom_killed,
            image=self.image.reference,
        )
