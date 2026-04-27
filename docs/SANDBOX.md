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

## Devcontainer support (v0.2)

If the repo has `.devcontainer/devcontainer.json` or `.devcontainer.json`
at root, that **takes precedence** over the ecosystem-default image. It's
the closest thing to "the canonical run environment for this repo" —
honouring it gives us better predictive value for how an agent will
actually behave on the team's setup.

Resolution flow:

1. Parse the devcontainer file as JSONC (comments + trailing commas
   permitted). Reject silently and fall back to ecosystem default if
   parsing fails — surface a Flow finding `devcontainer.unparseable`.
2. If `dockerComposeFile` is present → **hard fail** the runtime
   portion (see "Docker-native repos" below). The repo wants
   docker-socket access we don't grant in v0.
3. If `image:` is present → use that image directly under our normal
   sandbox rules.
4. If `dockerFile:` (or `build:`) is present:
    - **If the `devcontainer` CLI is on PATH** (`@devcontainers/cli`),
      shell out to it (`devcontainer up`, `devcontainer exec`). It
      handles `features`, `postCreateCommand`, etc. Use this path by
      default when available.
    - **If not**, do a plain `docker build` of the referenced
      Dockerfile and use the resulting image. Skip `features`,
      `postCreateCommand`, and other lifecycle hooks, and surface a
      Flow finding `devcontainer.partial_support` so the user knows
      they're getting a degraded run. Recommend installing the
      devcontainer CLI in the message.
5. `containerEnv` from devcontainer.json is allowlisted into the
   container. `mounts`, `forwardPorts`, `runArgs` are **ignored** in
   v0 — we control the host-level container config; honoring
   arbitrary `runArgs` would defeat the sandbox.

The two-phase model still applies: lifecycle hooks like
`postCreateCommand` run in the **setup** phase (network on); the
detected test command runs in the **test** phase (network off, unless
overridden).

Building a devcontainer image is slow (often minutes). The CLI prints a
clear progress banner, caches the built image by content hash, and
respects `--timeout-build` (default 600s) separately from the per-phase
timeout.

## Docker-native repos (hard fail)

Some repos *are* their own sandbox — they expect tests to run via
`docker compose up`, build a stack of services, and need access to the
host docker socket to do it. Sandboxing that safely is out of scope for
v0; pretending we can would produce misleading numbers.

Detection signals (any one is sufficient):
- `dockerComposeFile` in `devcontainer.json`
- A `docker-compose.yml` / `compose.yml` at root *and* a detected test
  command that invokes `docker compose` / `docker-compose`
- Detected test command (Makefile target, npm script, etc.) shells out
  to `docker run` / `docker build` / `docker compose`

Behaviour when detected and `--run` is passed:
- Exit 2 with: "This repo's tests rely on Docker (compose / docker-in-docker).
  agent-readiness v0 doesn't sandbox this safely. Re-run without `--run`
  for static analysis only."
- A Flow finding `flow.docker_native_unsupported` is emitted regardless
  (i.e., even on a static scan), so the static report still flags this
  as "you won't be able to use `--run` here yet."

We do **not** ship a `--privileged` opt-in or a `--mount-docker-socket`
flag in v0. Same logic as `--no-sandbox`: easy to relax later, hard to
tighten once shipped.

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
| Docker-native repo detected with `--run` | 2 | "This repo's tests rely on Docker (compose / docker-in-docker). agent-readiness v0 doesn't sandbox this safely. Re-run without `--run` for static analysis." |
| Devcontainer parses, but uses `dockerComposeFile` | 2 | Same as above — surfaced as docker-native. |
| Devcontainer present but `devcontainer` CLI missing | (run continues) | Finding: `devcontainer.partial_support`, severity warn. Build proceeds without features/lifecycle hooks. |
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
- A `--privileged` or `--mount-docker-socket` opt-in for docker-native
  repos. Detected and refused, not enabled.
