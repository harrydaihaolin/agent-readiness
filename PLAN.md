# Plan: agent-readiness CLI

## 1. North star

Given a repo path, output a score (and actionable report) for **how easily an
LLM coding agent can do useful work in this repo**. The output should make
maintainers go "oh, that's why our agent runs always go off the rails."

The metric we care about is *agent productivity*, not generic code quality.
A 100k-line monorepo with great `make`/`test`/AGENTS.md scaffolding can score
higher than a tiny, tidy library with no run instructions and a flaky test
suite.

## 2. Dimensions to measure

Grouped into six categories. Each category produces a 0–100 sub-score; overall
score is a weighted average.

### A. Onboarding & navigation (weight: high)
- README present, non-trivial, mentions purpose + how to run
- Agent-targeted docs: `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md`
- Entry points discoverable (main, bin/, cmd/, src/index.*)
- Directory tree depth & breadth sane (not 12 levels of `src/main/java/com/...`)
- Top-level file count not overwhelming

### B. Build / run / test reproducibility (weight: high)
- Recognised manifest (package.json, pyproject.toml, Cargo.toml, go.mod, etc.)
- Lockfile present
- A "run tests" command discoverable (Makefile target, npm script, `pytest`, `cargo test`)
- *(Optional, opt-in)* sandbox execution: actually try `make test` / `pnpm test` and time it
- `.env.example` if `.env` is referenced anywhere
- No hard-coded absolute paths

### C. Context-window economics (weight: medium)
- Distribution of file sizes; flag files >2k LOC or >50k tokens (rough char→token estimate)
- Largest function/class size (via lightweight AST per language)
- "Read budget to understand the repo": estimate tokens for README + manifest + top N files
- Generated/vendored code identified and excluded (node_modules, dist/, .min.js)

### D. Feedback-loop quality (weight: medium)
- Type-checker config (tsconfig, mypy, pyright, etc.)
- Linter/formatter config (eslint, ruff, prettier, gofmt)
- Test count and rough test/source ratio
- Test framework detected
- *(Optional)* time-to-first-test-result when sandbox run is enabled
- CI config present (.github/workflows, etc.) — agents can mimic CI locally

### E. Change locality (weight: medium)
- Cyclomatic complexity hot-spots (radon/lizard)
- Duplication estimate (token-based)
- Average files-changed-per-commit over last N commits (proxy for coupling)
- Module fan-in/fan-out where cheap to compute (Python imports, JS imports)

### F. Safety & hygiene (weight: low–medium)
- Secrets scan (basic regex pass; flag, don't fix)
- `.gitignore` covers common junk (`.env`, build artifacts)
- Dependency audit if cheap (`npm audit --json`, `pip-audit`)
- License file present

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
  `Finding` has `id`, `category`, `severity`, `score_delta`, `file?`, `line?`,
  `message`, `fix_hint?`.
- **RepoContext** is built once: file inventory, language detection,
  manifest parse, git log summary, cached AST per language. Checks read from
  this rather than re-walking the tree.
- **Scorer** rolls findings into category scores and an overall score; weights
  configurable.
- **Renderers**: terminal (rich), JSON, HTML, markdown.
- **Sandbox runner** (opt-in, off by default): runs detected build/test commands
  in a subprocess with timeout; captures duration and exit code only.

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

**v0.2 — `--run` (sandbox runner)**
- Detect a test command in priority order:
  Makefile `test` target → `package.json` scripts.test → `pyproject.toml`
  `[tool.pytest.ini_options]` → `Cargo.toml` → `go.mod` → `Gemfile` →
  fall back to "no test command found".
- Execute under `subprocess` with a timeout (default 300s) and a hard kill;
  capture exit code, duration, last 80 lines of output.
- Loud opt-in banner: `--run` prints what it's about to execute and waits
  for `y` unless `--yes`.
- Two new checks: `run.test_command_detected` and `run.tests_pass`
  (only scored when `--run` is on).

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
