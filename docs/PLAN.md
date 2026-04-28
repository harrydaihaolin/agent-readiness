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

(Cognitive-load checks `naming.search_precision` and `repo_shape.directory_depth`,
and feedback check `tests.determinism_proxy`, land in v0.35+.)

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

## 6. Phased roadmap

Decisions baked in: Python CLI, language-agnostic v0.1, `--run` lands in
v0.2, Docker-enforced sandboxing, devcontainer-first image resolution,
hard fail on docker-native repos, headless-first design lens.

### Phase 1 — v0.1: walking skeleton, 5 benchmarks

Goal: a working static scanner that produces a real, defensible score on
real repos, end-to-end. Five benchmarks chosen for **high predictive
signal × easy to target**: file/text/regex checks only, no AST work, no
language-specific parsing. Each spans a pillar so the score actually
moves between repos.

| # | Check id | Pillar | What it measures |
|---|---|---|---|
| 1 | `readme.has_run_instructions` | Cognitive load | README explains how to install and run (regex for install/run/test verbs; fenced code blocks; presence of common command tokens). |
| 2 | `agent_docs.present` | Cognitive load | At least one of `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md` exists at root. |
| 3 | `test_command.discoverable` | Feedback | A test invocation is discoverable without running anything: Makefile `test` target / `package.json` `scripts.test` / pytest config / `Cargo.toml` / `go.mod` / `Gemfile` / `scripts/test*`. |
| 4 | `headless.no_setup_prompts` | Flow | Repo's documented setup is non-interactive: README/scripts don't gate on a TTY-only step (heuristic: no "open the dashboard", "click", "log in to", "wizard" in setup-adjacent prose; `scripts/setup*` exists or install is one command). |
| 5 | `secrets.basic_scan` | Safety (cap) | No real-looking secrets in tracked files (AWS access keys, GitHub PATs, private-key PEM headers, generic high-entropy strings near keywords like `api_key`/`secret`). |

Plus the v0.1 infrastructure to make those five work and be extended:
- `Check` protocol + registry (`@register` decorator).
- `Scorer` rolling findings into pillar scores; safety as a cap.
- Renderers: terminal (rich) and JSON. Both stable; JSON schema
  versioned (`"schema": 1`) so consumers can pin.
- Static-only `flow.docker_native_unsupported` finding emitted when a
  Docker-native repo is detected (so users see it in v0.1 even though
  `--run` isn't built yet).
- Fixture repos: `tests/fixtures/good/`, `tests/fixtures/bare/`. Snapshot
  tests confirm they score noticeably differently. (Two fixtures, not
  three — `messy` adds little signal beyond `bare` at this scale.)

Out of Phase 1 (deferred to v0.2+): `--run`, manifest detection beyond
test-command discovery, repo-shape metrics (large files, top-level
count), gitignore quality, complexity, churn, type-checker / linter
detection, devcontainer support, HTML reports.

### Phase 2 — v0.2: `--run` with Docker-enforced sandbox
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
- **Three additional static checks** landed in v0.2 because the
  manifest-parsing infrastructure is shared with image resolution:
  `manifest.detected`, `manifest.lockfile_present`, `git.has_history`.

### Phase 3 — v0.3: context-window economics
File size distribution, token estimation (chars/4 heuristic, swap to
tiktoken later), large-file flagging, "tokens to grok this repo" budget
(README + manifest + top-N entry points). Repo-shape metrics
(`repo_shape.top_level_count`, `repo_shape.large_files`,
`repo_shape.directory_depth`).

### Phase 3.5 — v0.35: flow completeness (remaining static checks)
Lands the rubric-table checks that have no phase home yet. All are
static-only (file walk / regex / git read); no Docker required.

| Check | Pillar | Signal |
|---|---|---|
| `entry_points.detected` | Cognitive load | `main.py`, `index.js`, `cmd/`, `bin/`, `src/index.*` discoverable |
| `env.example_parity` | Flow | If any file reads `os.environ` / `process.env`, `.env.example` must exist with keys (no values) |
| `ci.configured` | Feedback | One of: GitHub Actions, CircleCI, Buildkite, Travis CI, Jenkins, GitLab CI, Azure Pipelines, Bitbucket Pipelines, AppVeyor, Drone CI, Woodpecker CI, Earthly |
| `setup.command_count` | Flow | Count setup steps in README; >3 distinct commands is a finding |
| `naming.search_precision` | Cognitive load | Count of files matching ambiguous terms (`utils`, `helpers`, `manager`); high counts degrade grep precision |

After v0.35 every check in the checks→pillars table above has a phase
home and the rubric has no orphaned rows.

### Phase 4 — v0.4: feedback signals beyond test-command
Detect type-checker / linter configs by filename (`mypy.ini`, `.mypy.ini`,
`pyrightconfig.json`, `tsconfig.json`, `.eslintrc*`, `ruff.toml`, etc.).
Add headless-walkability checks beyond setup: error-message-quality
heuristic (`assert` without messages, bare `except`, stringly-typed
exceptions), status-command discoverability. `gitignore.covers_junk`
lands here (build artefacts, IDE config, OS noise).

### Phase 5 — v0.5: complexity and churn
Cross-language cyclomatic complexity via `lizard` (Python, JS/TS, Go,
Java, C/C++). Per-commit churn from `git log --numstat` — files with
high churn and high complexity are the agent failure hotspots. Findings
surface the top-N hot files with churn × complexity scores.

### Phase 6 — v0.65: CLI surface and configurability
Completes the full CLI surface described in § 3 above.
- `agent-readiness init` — writes `.agent-readiness.toml` with
  commented defaults for every configurable option.
- `.agent-readiness.toml` reading — `RepoContext` picks up
  `[ignore]` patterns; scorer picks up `[weights]` overrides.
- `--weights weights.toml` — per-invocation pillar weight overrides.
- `--only A,B` — filter to specific check IDs or pillar names;
  headless-friendly for CI pipelines that only care about one pillar.
- `--baseline base.json` — diff vs a previous `--json` run; output
  includes delta per pillar and per check, and a `+/-` overall.

### Phase 7 — v0.7: HTML report and per-language depth
`--report report.html` (jinja2). Tree-sitter integration for Python and
TS first; better function/class size measurement, import-graph
fan-in/fan-out, per-language directory depth.

### Phase 8 — v0.8: validation study and distribution
The benchmark study described in RUBRIC.md § Validation strategy,
now assigned a phase:
- Assemble 10–20 repos spanning "obviously ready" to "obviously rough."
- Run a fixed task suite (small refactor, add feature, fix seeded bug)
  with one or two coding agents; measure task success rate.
- Check that `agent-readiness` score correlates with success rate; cut
  checks that don't move with outcomes, adjust weights.
- **pipx / PyPI publish** — `pipx install agent-readiness` works end-to-end.
- **GitHub Actions step** — `uses: <org>/agent-readiness-action@v1`
  that runs `scan --json` and optionally fails below a threshold score.
- **Score badge generation** — `--badge badge.svg` writes a shields-style
  SVG for embedding in README.

### Phase 9 — v1.0: plugin API and stable contract
- **Custom-check plugin mechanism** — drop modules into
  `.agent_readiness_checks/` or register via `entry_points`; tool
  discovers and runs them alongside built-ins.
- **SARIF export** — `--sarif findings.sarif` so findings integrate into
  the GitHub code-scanning UI and PR annotations.
- **`--fail-below N`** exit-code mode for CI gates (exits 1 if overall
  score < N).
- **Schema v2 declaration** — intentional breaking-change window; v1
  consumers get a migration guide. After v1.0 the JSON schema is stable.

## 7. Risks / open questions

1. **Polyglot repos.** Heuristics per language explode. Phase 1 stays
   strictly language-agnostic; per-language depth lives in Phase 6.
2. **Score gaming.** Once a number exists, people optimise it. Every
   check ships with an `explain` entry tying it to a concrete agent
   failure mode — that's the discipline.
3. **What counts as "agent ready" is opinion.** We publish the rubric
   and weights and let users override via `.agent-readiness.toml`.
4. **Headless heuristics are fuzzy.** "No interactive setup" via README
   regex will have false positives/negatives. Phase 1 ships the coarse
   version; Phase 4 sharpens it.
5. **Validation lag.** The benchmark study that validates the rubric
   (see RUBRIC.md § Validation strategy) doesn't run until we have
   v0.3-ish. Until then, the rubric is a hypothesis.
