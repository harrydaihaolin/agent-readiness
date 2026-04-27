# Sandbox

Any check that **executes code from the target repo** runs inside a Docker
container. No exceptions, no host-fallback. Static checks (file walking,
parsing manifests, regex scans, git log reads) run on the host as before.

This document captures the design and the choices it forces.

## Why enforced, not opt-in

1. **Safety.** Repos under analysis are untrusted. A `Makefile`, a
   `package.json` `postinstall`, or a `pytest` conftest can run arbitrary
   code. Sandboxing the execution path is the only honest default.
2. **Comparability.** A "tests took 47s" number is meaningless if it was
   measured on someone's M3 Max vs a 2017 ThinkPad. A fixed-image baseline
   makes scores comparable across users and machines.
3. **Reproducibility.** Same image, same repo, same score (modulo
   non-deterministic tests, which is itself a finding we want to surface).
4. **Cleanup.** Tests leave files, processes, ports. Containers are
   throwaway by construction.

## Hard contract

- `--run` **requires** a working Docker daemon. If `docker version`
  fails, `agent-readiness scan --run` exits 2 with a clear message and a
  link to install instructions. It does not silently fall back to host
  execution.
- There is **no `--no-sandbox` escape hatch in v0.** We can add one later
  if real users hit a real blocker; making it work strict first is
  cheaper than retrofitting strict onto a permissive default.
- Static-only scans (without `--run`) work without Docker.

## Image strategy

We pick an image based on the manifest detected in `RepoContext`. Each
default is a pinned digest, not a floating tag, so that a v0.1.0 of the
CLI scores the same way next year.

| Ecosystem detected | Default image (pinned digest) |
|---|---|
| `pyproject.toml` / `requirements.txt` | `python:3.12-slim@sha256:…` |
| `package.json` (no other) | `node:20-slim@sha256:…` |
| `go.mod` | `golang:1.22@sha256:…` |
| `Cargo.toml` | `rust:1.78-slim@sha256:…` |
| `Gemfile` | `ruby:3.3-slim@sha256:…` |
| Polyglot or unknown | `mcr.microsoft.com/devcontainers/universal:2@sha256:…` |

Override via `--image <ref>` or `[sandbox] image = "..."` in
`.agent-readiness.toml`.

A nice future extension (parked for v0.5+): if the repo has a
`.devcontainer/devcontainer.json`, prefer that — it's the closest thing
to "the canonical run env for this repo" — but only when the user opts
in via `--devcontainer`, since building a devcontainer image is slow.

## Container configuration

Defaults, all overridable via config:

- `--rm` (always — no stale containers on the host).
- `--read-only` rootfs, with `--tmpfs /tmp:size=512m` for ephemeral writes.
- Repo mounted at `/repo`, **read-only**. If a check needs a writeable
  copy (e.g., a build that writes alongside source), we copy in via a
  named volume rather than relax the host mount.
- `--memory=2g --cpus=2 --pids-limit=512` baseline limits. Overridable.
- **Network: default deny for test execution** (`--network=none`).
  Setup/install phases that need to fetch dependencies run in a
  separate, network-allowed phase. This split is the v0 default; we'll
  revisit if it forces too many opt-outs.
- Wall-clock timeout (default 300s) enforced by us, not just Docker —
  we kill the container if it blows the budget.
- No host env vars passed through. Repo's own `.env.example` is *read*
  for parity checks but never sourced into the container.

## Two-phase execution

For ecosystems that need installation before tests can run:

1. **Setup phase.** Network allowed. Runs the detected install command
   (`pip install -e .`, `npm ci`, `go mod download`, `cargo fetch`, etc.).
   Captures duration, exit code, last 80 lines of output.
2. **Test phase.** Network denied. Runs the detected test command. Same
   capture.

Both phases produce findings:
- `setup.runs` and `setup.duration` → Flow pillar
- `test_command.runs` and `test_command.duration` → Feedback pillar

If setup fails, the test phase is skipped and `test_command.runs` is
scored 0 with a finding pointing at the setup failure.

## Failure modes (and the messages we show)

| Condition | Exit | Message |
|---|---|---|
| `docker` binary not found | 2 | "Docker is required for `--run`. Install: https://docs.docker.com/get-docker/" |
| Docker daemon not reachable | 2 | "Docker is installed but the daemon isn't reachable. Start Docker Desktop or `systemctl start docker`." |
| Image pull fails | 2 | "Could not pull `<image>`. Check your network or `docker pull <image>` directly." |
| Container OOM-killed | (run completes) | Finding: `setup.oom` or `test_command.oom`, severity error. |
| Wall-clock timeout | (run completes) | Finding: `…timed_out`, severity error, with the budget that was hit. |
| Repo writes to mounted source | (run completes) | Finding: `sandbox.repo_writes_attempted`, surfaces what tried to write. |

## What this means for the rubric

- The Feedback pillar's runtime checks (`test_command.runs`,
  `test_command.duration`, `setup.runs`, `setup.duration`,
  `tests_pass`) **only score when `--run` is enabled**. Without `--run`,
  those slots in the pillar are marked `not measured` rather than
  scored 0 — otherwise every static scan would unfairly tank Feedback.
- We will publish two reference scores: **static** (no `--run`) and
  **full** (with `--run`). They are not interchangeable. The static
  score is a lower-bound estimate of agent operability.

## Out of scope for v0

- Apple Silicon multi-arch image handling beyond what Docker Desktop
  does for us.
- Docker-in-Docker / sibling-container support inside a CI runner
  (probably works via `/var/run/docker.sock` mount, but we don't
  document it as supported in v0).
- Podman, Lima, Finch, or rootless alternatives. We'd take a PR; we
  won't drive it.
- Honoring `.devcontainer/devcontainer.json`. Parked for v0.5+.
