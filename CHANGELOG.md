# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)

## [Unreleased]

## [1.1.0] - 2026-04-29

### Added
- `agent_readiness.rules_eval/`: reference (OSS) evaluator for the
  declarative YAML rule format defined by
  `agent-readiness-insights-protocol`. Implements the five OSS match
  types (`file_size`, `path_glob`, `manifest_field`, `regex_in_files`,
  `command_in_makefile`). Unknown match types (e.g. `ast_query` from
  the closed engine) are dropped with `not_measured=True` rather than
  raising — Bronze stays usable when a rule pack is forward-compatible.
- `agent_readiness.rules_pack/`: vendored copy of
  [`agent-readiness-rules`](https://github.com/harrydaihaolin/agent-readiness-rules)
  v1.0.0 (7 rules across cognitive_load / feedback / flow). Refresh via
  `scripts/vendor_rules.sh <tag>`; the script writes a `MANIFEST` with
  the source tag and tarball SHA for traceability.
- `agent-readiness rules-eval <path>`: new diagnostic CLI command.
  Runs only the rules-pack evaluator (not `@register` checks). Used by
  `agent-readiness-rules` CI and by developers iterating on rules.
- `scan --with-rules`: opt-in flag that merges rules-pack findings into
  the regular scan output. Planned to become the default in 1.2.0
  after observing impact on real-world scores.
- `scan --rules-dir DIR`: override the vendored pack with a local
  directory. Useful for rule authors testing changes before tagging.

### Changed
- New runtime deps: `pyyaml>=6` (rule loading) and
  `agent-readiness-insights-protocol>=0.1,<1.0` (shared schema).
  Both are tiny pure-Python deps with no transitive baggage.
- `pyproject.toml` now packages `src/agent_readiness/rules_pack/**/*.yaml`,
  `MANIFEST`, and `manifest.toml` into the wheel via `tool.hatch.include`.

### Notes for downstream
- `PROTOCOL_VERSION = 1` and `RULES_VERSION = 1` are unchanged; this
  release is purely additive on the protocol surface.

## [1.0.0] - 2026-04-28

### Added
- `scan` shows a per-check progress visualizer on stderr (rich when
  available, plain `\r` fallback otherwise). Auto-disabled for `--json`
  and non-TTY stderr; opt-out with `--no-progress`. Stdout contract
  (report / JSON) is unchanged.
- `ci.configured`: detect Earthly (`Earthfile`), Drone CI
  (`.drone.yml` / `.drone.yaml`), and Woodpecker CI
  (`.woodpecker.yml` / `.woodpecker.yaml` / `.woodpecker/`). Reported
  by users running monorepos where the in-repo build recipe is Earthly
  but the trigger lives in an external orchestrator.

### Changed
- `ci.configured`: refactored to a data-driven detector list and a
  unified message format: `"CI configuration detected: <label>."`
  Previous per-detector ad-hoc messages are gone. Score behaviour is
  unchanged for all previously-detected configs.
- First stable PyPI release. Version bumped to 1.0.0 to reflect
  complete implementation of all nine phases (Plugin API, SARIF,
  stable JSON schema v1).

## [0.9.0] - Phase 9: Plugin API, SARIF, stable contract

### Added
- Custom check plugins via `.agent_readiness_checks/` directory (local plugins)
- Entry-point plugins via `agent_readiness.checks` group in `importlib.metadata`
- SARIF 2.1.0 export (`--sarif FILE`) for GitHub Code Scanning integration
- `Report.delta` field for baseline comparison
- `Report.schema=1` stability documentation (will bump to 2 on next breaking change)

### Changed
- Plugin loading happens before `_ensure_loaded()` so plugins register cleanly
- `models.py`: add `delta` field to Report for `--baseline` delta display

## [0.8.0] - Phase 8: Distribution

### Added
- PyPI classifiers and keywords in `pyproject.toml`
- `.github/workflows/ci.yml` for the project itself (lint + test + dogfood scan)
- `validate/README.md` describing the planned validation study methodology

## [0.7.0] - Phase 7: HTML report renderer and badge generation

### Added
- `src/agent_readiness/renderers/html_renderer.py`: Jinja2-based HTML report
  (optional dep: `pip install agent-readiness[report]`)
- `src/agent_readiness/renderers/sarif.py`: SARIF 2.1.0 export
- CLI `--report FILE`: write HTML report
- CLI `--badge FILE`: write shields.io-style SVG badge
- CLI `--sarif FILE`: write SARIF output

## [0.65.0] - Phase 6: CLI surface and configurability

### Added
- `init` command: writes `.agent-readiness.toml` with commented defaults
- `src/agent_readiness/config.py`: load and parse `.agent-readiness.toml`
- CLI `--weights FILE`: override pillar weights from a TOML file
- CLI `--only CHECKS`: filter to specific check IDs or pillar names
- CLI `--baseline FILE`: load previous JSON report and show score delta
- CLI `--fail-below N`: exit 1 when overall score < N (CI gate)

## [0.5.0] - Phase 5: Complexity and churn

### Added
- `git.churn_hotspots` check (CogLoad, weight=0.6): files changed >10 times
  AND >200 lines are flagged as hotspots; `not_measured` if <5 commits
- `code.complexity` check (CogLoad, weight=0.7): cyclomatic complexity via
  lizard; `not_measured` if lizard not installed
- Optional extras in `pyproject.toml`: `report`, `complexity`, `full`

## [0.4.0] - Phase 4: Feedback signals

### Added
- `typecheck.configured` check (Feedback, weight=0.9): mypy.ini, pyrightconfig.json,
  tsconfig.json, or `[tool.mypy]` in pyproject.toml
- `lint.configured` check (Feedback, weight=0.9): ruff.toml, .eslintrc, .golangci.yml,
  or `[tool.ruff]` in pyproject.toml
- `gitignore.covers_junk` check (Safety, weight=1.0): .gitignore covering
  __pycache__, .env, node_modules, dist/
- Good fixture: mypy.ini, ruff.toml, .gitignore

## [0.35.0] - Phase 3.5: Flow completeness

### Added
- `entry_points.detected` check (CogLoad, weight=0.8): main.py, index.js, cmd/, etc.
- `env.example_parity` check (Flow, weight=0.9): .env.example when env vars used
- `ci.configured` check (Feedback, weight=0.9): GitHub Actions, CircleCI, etc.
- `setup.command_count` check (Flow, weight=0.7): ≤2 setup commands is ideal
- `naming.search_precision` check (CogLoad, weight=0.6): no utils/helpers/manager
- Good fixture: .github/workflows/ci.yml, src/main.py, src/__init__.py, .env.example
- Good fixture now scores 100.0 overall

## [0.3.0] - Phase 3: Context-window economics and repo shape

### Added
- `RepoContext.orientation_tokens` cached property (chars/4 heuristic)
- `repo_shape.top_level_count` check (CogLoad, weight=0.8)
- `repo_shape.large_files` check (CogLoad, weight=0.8)
- `repo_shape.token_budget` check (CogLoad, weight=0.7)

## [0.2.0] - Phase 2: Docker sandbox and static manifest checks

### Added
- `manifest.detected` check (Feedback, weight=1.0): pyproject.toml, package.json, etc.
- `manifest.lockfile_present` check (Feedback, weight=1.0): poetry.lock, uv.lock, etc.
- `git.has_history` check (Flow, weight=1.0): scores by commit count
- Full `DockerSandbox.run()`, `detect_docker_native()`, `resolve_image()` implementations
- `src/agent_readiness/config.py`: load `.agent-readiness.toml`
- `src/agent_readiness/plugins.py`: plugin discovery
- CLI `--run` flag fully implemented (preflight → docker-native check → run)
- Good fixture: pyproject.toml, uv.lock, CLAUDE.md
- Fixed `RepoContext.is_git_repo` to detect parent-repo git via `git rev-parse`

## [0.1.0] - Phase 1: Five static checks

### Added
- `readme.has_run_instructions` check (CogLoad, weight=1.0)
- `agent_docs.present` check (CogLoad, weight=1.0)
- `test_command.discoverable` check (Feedback, weight=1.0)
- `headless.no_setup_prompts` check (Flow, weight=1.0)
- `secrets.basic_scan` check (Safety, weight=1.0): caps overall at 30 on ERROR, 75 on WARN
- `RepoContext`: cached file inventory, git helpers
- `scorer.score()`: weighted pillar means + safety cap
- Terminal renderer (rich + plain-text fallback)
- JSON renderer (stable schema v1)
- `scan`, `list-checks`, `explain` CLI commands
- Good and bare test fixtures
- Safety cap behaviour tests

[Unreleased]: https://github.com/harrydaihaolin/agent-readiness/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v0.9.0...v1.0.0
[0.9.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v0.65.0...v0.7.0
[0.65.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v0.5.0...v0.65.0
[0.5.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v0.35.0...v0.4.0
[0.35.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v0.3.0...v0.35.0
[0.3.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/harrydaihaolin/agent-readiness/releases/tag/v0.1.0
