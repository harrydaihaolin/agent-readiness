# Plan: agent-readiness CLI

## 1. What we benchmark

See [`RUBRIC.md`](./RUBRIC.md) — the authoritative definition of agent
operability and our three-pillar scoring framework (cognitive load,
feedback loops, flow), plus a safety-and-trust cap. Every check below
maps to a pillar in the rubric; if it doesn't, it doesn't ship.

Product framing: a **DevEx benchmark for AI coding agents**. Lighthouse
for agent productivity. Audience: engineering leaders rolling out coding
agents who want to know why agents struggle on their codebase and what
to fix first.

## 2. Checks → pillars mapping

| Check id | Pillar | What it predicts |
|---|---|---|
| `readme.present` | Cognitive load | Agent can orient itself in the repo |
| `readme.has_run_instructions` | Cognitive load | Agent can find how to install / run |
| `agent_docs.present` | Cognitive load | Repo speaks to agents directly (CLAUDE.md, AGENTS.md, .cursorrules) |
| `repo_shape.top_level_count` | Cognitive load | Top-level isn't a dumping ground |
| `repo_shape.large_files` | Cognitive load | No mega-files that blow the context window |
| `entry_points.detected` | Cognitive load | Agent knows where execution starts |
| `manifest.detected` | Feedback loops | Recognised ecosystem (pyproject / package.json / etc.) |
| `manifest.lockfile_present` | Feedback loops | Reproducible installs |
| `test_command.discoverable` | Feedback loops | Agent can find how to run tests |
| `test_command.runs` (with `--run`) | Feedback loops | Tests actually execute |
| `test_command.duration` (with `--run`) | Feedback loops | Feedback latency |
| `typecheck.configured` | Feedback loops | Static signal pre-test |
| `lint.configured` | Feedback loops | Static signal pre-test |
| `ci.configured` | Feedback loops | Local-vs-CI parity exists |
| `env.example_parity` | Flow / reliability | Agent can fill in env from the example |
| `setup.command_count` | Flow / reliability | Steps from clone to green test |
| `git.has_history` | Flow / reliability | Real repo, not a snapshot |
| `gitignore.covers_junk` | Safety & trust | Agent won't accidentally commit build output |
| `secrets.basic_scan` | Safety & trust | No real-looking secrets in the tree |

(Cognitive-load checks like `naming.search_precision`, `repo_shape.directory_depth`,
and feedback checks like `tests.determinism_proxy` arrive in v0.2+.)

## 3. CLI surface

```
agent-readiness scan [PATH]            # default human report to stdout
  --json                                # machine-readable
  --report report.html                  # write HTML report
  --weights weights.toml                # override default category weights
  --run                                 # opt-in: actually execute build/test
  --only A,B                            # run only some categories
  --baseline base.json                  # diff vs a previous run
agent-readiness explain <check-id>      # what a check means + how to fix
agent-readiness list-checks             # all checks, by category
agent-readiness init                    # write a default .agent-readiness.toml
```

## 4. Architecture

- **Plugin model.** Each check is a class/function: `(RepoContext) -> list[Finding]`.
  `Finding` has `id`, `pillar`, `severity`, `score_delta`, `file?`, `line?`,
  `message`, `fix_hint?`.
- **RepoContext** is built once: file inventory, language detection,
  manifest parse, git log summary, cached AST per language. Checks read from
  this rather than re-walking the tree.
- **Scorer** rolls findings into pillar scores and an overall score; weights
  configurable. Safety findings act as a cap, not a weight.
- **Renderers**: terminal (rich), JSON, HTML, markdown.
- **Sandbox runner** (Docker-enforced; see [`SANDBOX.md`](./SANDBOX.md)). Any
  check that executes code from the target repo runs inside a pinned-image
  container with read-only repo mount, no host env, network split between
  setup and test phases, wall-clock timeout, and resource limits. There is
  no host-execution fallback in v0.

## 5. Tech stack (decided)

- **Python 3.11+** with `typer` (CLI), `rich` (terminal), `pydantic` (models),
  `jinja2` (HTML report later). Shell out to `git` rather than pulling in
  GitPython.
- v0.1 is language-agnostic, so **no `tree-sitter` / `lizard` yet** — those
  arrive when category D/E checks need real ASTs. Saves a heavy dep at v0.
- Ship via `pipx install agent-readiness`; fallback `python -m agent_readiness`.

## 6. Phased roadmap (revised after decisions)

Decisions baked in: Python CLI, language-agnostic v0.1, `--run` in v0.

**v0.1 — Walking skeleton with real signal**
Project scaffold (`pyproject.toml`, package layout, `agent-readiness --version`,
`typer` entry point), `RepoContext` (file walk with vendored/generated
exclusion, git log summary), and the following language-agnostic checks:
- `readme.present` and `readme.has_run_instructions` (regex for "install" /
  "run" / "test" / fenced code blocks)
- `agent_docs.present` (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`,
  `.github/copilot-instructions.md`)
- `manifest.detected` (which ecosystem + lockfile present?)
- `gitignore.present` and a coarse "covers common junk" check
- `repo_shape.top_level_count` and `repo_shape.large_files`
- `secrets.basic_scan` (regex pass for AWS keys, generic API keys, private
  key headers)
- `git.has_history` (commit count, recency)

Terminal renderer (rich) and JSON renderer both ship in v0.1. Snapshot tests
against 3 fixture repos in `tests/fixtures/`: `good/`, `bare/`, `messy/`.

**v0.2 — `--run` with Docker-enforced sandbox**
See [`SANDBOX.md`](./SANDBOX.md) for the full design. v0.2 implements:
- Docker availability preflight; hard fail if `docker version` fails.
- **Docker-native repo detection.** If the repo's tests need
  `docker compose` / docker-socket access (signals: `dockerComposeFile`
  in devcontainer, compose file referenced from test command, `docker`
  invocations in the test target), `--run` exits 2 with a clear
  message and a Flow finding `flow.docker_native_unsupported` is
  emitted on every scan (static or full).
- **Devcontainer-first image resolution.** If
  `.devcontainer/devcontainer.json` (or `.devcontainer.json`) exists:
  - `image:` → use directly under sandbox rules.
  - `dockerFile:` / `build:` → shell out to the `devcontainer` CLI
    when available (handles features + lifecycle hooks); otherwise
    plain `docker build` with a `devcontainer.partial_support`
    finding.
  - `dockerComposeFile:` → docker-native, hard fail (see above).
  - Honor `containerEnv`; ignore `mounts` / `runArgs` /
    `forwardPorts` (we control the sandbox surface).
- **Ecosystem-default image** (pinned digest) when no devcontainer:
  Python / Node / Go / Rust / Ruby; universal devcontainer image as
  polyglot fallback. Override via `--image`.
- **Test command detection** in priority order: Makefile `test` →
  `package.json` `scripts.test` → pytest config in `pyproject.toml` →
  `Cargo.toml` → `go.mod` → `Gemfile` → "not found".
- **Two-phase execution.** Setup (network on, runs install +
  `postCreateCommand`-style hooks) then test (network off). Each
  phase captures exit code, duration, and last 80 lines of output.
- **Wall-clock timeout** enforced by us, not just Docker. Repo
  mounted read-only at `/repo`; rootfs read-only with tmpfs `/tmp`.
- **New checks** (only scored when `--run` is on):
  `setup.runs`, `setup.duration`,
  `test_command.runs`, `test_command.duration`, `test_command.passes`.
- **Static-only findings** related to `--run` (always emitted,
  regardless of `--run`):
  `devcontainer.present`, `devcontainer.unparseable`,
  `flow.docker_native_unsupported`,
  `test_command.discoverable`.

**v0.3 — Context-window economics**
File size distribution, token estimation (chars/4 heuristic, swap to
tiktoken later), large-file flagging, "tokens to grok this repo" budget
(README + manifest + top-N entry points).

**v0.4 — Feedback-loop & complexity**
Detect type-checker / linter configs by filename. Add `lizard` for
cross-language cyclomatic complexity. Per-commit churn from git log.

**v0.5 — HTML report + baseline diff**
`--report report.html` (jinja2) and `--baseline base.json` for trend
tracking.

**v0.6 — Per-language depth**
Tree-sitter integration for Python and TS first; better function/class
size measurement, import-graph fan-in/fan-out.

## 7. Risks / open questions

1. **Polyglot repos.** Heuristics per language explode. v0.1 should pick
   *one* language well (Python or TS) and stub the rest.
2. **Sandbox safety.** `--run` executes arbitrary repo code. Needs explicit
   opt-in and ideally container isolation. Defer to v0.5.
3. **Score gaming.** Once a number exists, people optimise it. Each check
   needs a clear *why* in `explain` so the fix improves real ergonomics, not
   the metric.
4. **What counts as "agent ready" is itself an opinion.** We should
   publish the rubric and weights and let users override via config.
5. **Fixture repos for testing.** Need 4–5 small fixture repos (good, bad,
   polyglot, monorepo, no-tests) checked into `tests/fixtures/`.

## 8. Suggested first commits after this plan

1. `pyproject.toml` + package skeleton + `agent-readiness --version`
2. `RepoContext` + file walk
3. First check: `readme_present` + terminal renderer
4. Fixture repo + snapshot test
