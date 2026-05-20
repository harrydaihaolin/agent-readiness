# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)

## [Unreleased]

## [2.4.1] - 2026-05-20

The "language tables catch up to the prompt prose" release. Pairs the
engine probe tables and the freshly-vendored rules pack so the
rendered `fix_prompt` prose stays correct on non-Python/non-JS repos.
No behaviour change for projects already covered by the v2.4.0
tables.

### Added (engine)

- `_LANGUAGE_BY_MANIFEST` expanded from 16 → 27 manifest -> language
  entries: now covers Pipfile, build.sbt (Scala), pubspec.yaml (Dart),
  stack.yaml + cabal.project (Haskell), deps.edn (Clojure modern),
  rebar.config (Erlang), dune-project (OCaml), Project.toml (Julia),
  DESCRIPTION (R), CMakeLists.txt (C++), Makefile.PL + cpanfile (Perl).
- `_LANGUAGE_TEST_COMMAND` / `_LINT` / `_INSTALL` tables expanded to
  cover ~20 languages (was 10/7/7). Adds php, scala, dart, haskell,
  clojure, erlang, ocaml, julia, r, cpp, perl + fills in lint/install
  gaps for kotlin and swift.
- `_LOCKFILE_PACKAGE_MANAGER` expanded from 12 → 22 entries: adds pdm,
  conda-lock, pixi, mix.lock, pubspec.lock, Package.resolved,
  stack.yaml.lock, cabal.project.freeze, flake.lock, npm-shrinkwrap.
- File-extension fallback in `_detect_primary_language` expanded from
  7 → 27 extensions, so non-manifest repos (e.g. a vendored Erlang
  script collection) still get a language pick that downstream
  `{language_*_command}` placeholders can render against.

### Changed (vendored rules)

- Re-vendored `agent-readiness-rules` from **v2.1.0 → v2.2.0**
  (`scripts/vendor_rules.sh v2.2.0`). Highlights of the upstream change:
  - `ci.configured` detection list grew from 19 to 50+ provider
    config paths (AWS CodeBuild, Codemagic, Wercker, Screwdriver,
    Concourse, Argo Workflows, Harness, Tekton, Skaffold, Garden,
    plus Forgejo/Gitea workflow paths).
  - 14 rule `fix_prompt` bodies refactored from "For Python: X. For
    JS/TS: Y." → "For your {primary_language} project: ..." plus a
    bulleted enumeration of 7-13 language choices.
  - `manifest.lockfile_present` action.command is now a guarded shell
    `case` over `{package_manager}` that no-ops on undetectable
    repos instead of executing the broken `lock` / `install
    --frozen-lockfile` tokens that crashed v2.1.0 dogfood runs.

### Why

The rules pack v2.2.0 renders fix_prompts that lead with
`{primary_language}` + `{language_test_command}` /
`{language_install_command}` / `{package_manager}`. Before this
release those placeholders fell back to a generic phrase on anything
that wasn't already in the engine's 10-language table; this release
lets them resolve concretely on the long tail (Swift, Kotlin,
Scala, Elixir, Dart, Haskell, OCaml, Clojure, Erlang, Julia, R,
C++, Perl, PHP).

### Not changed

- Protocol pin (`>=0.1,<1.0`). Still relaxed; will re-tighten once
  protocol v0.4.x lands on PyPI (currently blocked on trusted-publisher
  registration).

## [2.4.0] - 2026-05-20

The "actually-apply-the-pin" release. Closes the loop on EXP-4
(top_action pin) by restoring the executor side of the contract:
`apply_top_action()` materialises one structured fix in the working
copy and optionally runs the rule's `verify` command. The CLI
exposes this as `agent-readiness scan --apply-top-action [--verify]`,
which is the contract the dogfood workflows in
`agent-readiness-mcp`, `agent-readiness-pro`, and
`agent-readiness-action` template against.

### Added
- **`agent_readiness.apply_action` module.** A new top-level module
  exposing `apply_top_action(top_action, repo, *, run_verify=True)
  -> ApplyResult`. Dispatches on `top_action["action"]["kind"]` to
  six handlers covering every action kind defined in
  `agent_readiness_insights_protocol.models`:
  - `create_file` — write a brand-new file from `template`; refuses
    to overwrite an existing path so retries are safe.
  - `append_to_file` — append `template`, creating the file if
    absent; inserts a separator when the existing file ends without
    a newline.
  - `insert_after` — match `after_pattern` with `re.MULTILINE` and
    inject `template` right after the matched line.
  - `edit_gitignore` — append missing entries to `.gitignore`;
    idempotent when every entry is already present
    (returns an empty `written` list).
  - `modify_manifest_field` — set a dotted field inside a
    structured manifest. JSON and YAML are parse-edit-rewrite; TOML
    follows the protocol's "append a fresh table if the field is
    missing" contract so we don't need a TOML writer dep.
  - `run_command` — execute the structured shell command in the
    repo root with a 60 s timeout.
  Each handler returns the list of repo-relative paths it touched
  (or `[]` for `run_command` and idempotent no-ops). All handlers
  run through a path-escape guard that refuses absolute paths and
  `..` traversal.
- **`ApplyResult` envelope.** `dataclass` with `applied`, `written`,
  `verified`, `verify`, `skipped_reason`, `error`. `to_dict()`
  strips `None`/empty fields so the emitted JSON matches the
  convention `report.to_dict()` already uses. Handlers never raise
  out of `apply_top_action` — every error path returns an envelope
  with `applied=False` and `error="ExcClass: message"`.
- **Verify subprocess runner.** When `run_verify=True` and the
  top_action ships a non-empty `verify.command`, the engine runs it
  via `subprocess.run(shell=True, cwd=repo, timeout=...)`. The
  envelope captures `command`, `exit_code`, and the trailing 2 KB
  of stdout/stderr; `verified` is set to `proc.returncode == 0`.
  Timeouts surface as `verify={"timed_out": True, ...}, verified=False`.
- **`scan --apply-top-action [--verify]` CLI flags.** Adds two
  flags to `agent_readiness.cli scan`:
  - `--apply-top-action` runs the executor on `report.top_action`
    after rendering the scan report. JSON output gains an
    `apply_top_action` key in a separate envelope (printed after
    the report) so consumers can tell scan output from apply
    output. Plain output prints `Applied top action; wrote: …` or
    `Apply skipped: …` / `Apply failed: …` on stderr.
  - `--verify` is only meaningful with `--apply-top-action`. When
    set, exits 1 if the verify command fails. Together with
    `--fail-below`, this gives CI a single command that gates on
    "scan passes AND top fix lands AND verify confirms the rule
    stops firing".
- **`tests/test_apply_action.py`** (29 cases). Covers every action
  kind, the path-escape guard, the verify-pass/verify-fail/verify-
  skipped paths, idempotency for `edit_gitignore` and TOML
  `modify_manifest_field`, and `ApplyResult.to_dict()`
  serialisation.

### Notes
- Restores parity with the contract the dogfood workflows were
  templated against in 2026-04 — they have shipped with
  `--apply-top-action --verify` referenced in comments since
  Phase C8 even though the engine did not actually expose those
  flags. Workflows that disabled the flags as a workaround
  (agent-readiness-mcp's dogfood, agent-readiness-pro v2.1.0's
  dogfood) can re-enable them once they bump their engine pin to
  `>=2.4.0`.
- MCP server: `agent_readiness_mcp.server.apply_top_action`'s
  lazy `from agent_readiness.apply_action import apply_top_action`
  now succeeds. The xfail in `agent-readiness-mcp/tests/test_server.py`
  on `test_apply_top_action_returns_result_envelope` should now
  flip to xpass; the MCP repo will drop the xfail in a follow-up.
- Tracking issue: `harrydaihaolin/agent-readiness-mcp#1`.

## [2.3.1] - 2026-05-20

### Fixed
- Relax `agent-readiness-insights-protocol` pin from `>=0.4,<1.0`
  back to `>=0.1,<1.0`. Same root cause as the 2.1.1 fix: protocol
  v0.4.0 (which adds the optional `fix_prompt` property the engine
  now renders) exists as a git tag and GitHub release but is not
  yet on PyPI, so `pip install agent-readiness==2.3.0` from a fresh
  environment failed dependency resolution. The engine only imports
  `Rule` for best-effort validation in `rules_eval/loader.py`
  (wrapped in try/except, debug-logs and continues on rejection),
  so protocol v0.1.0 is sufficient at runtime. Re-tighten this pin
  once protocol v0.4.0 is on PyPI.

## [2.3.0] - 2026-05-20

The "paste-ready friction-fix" release. Every `Finding` that
matches a v2 rule with an authored `fix_prompt:` block now carries
the rendered natural-language instruction inline, so a user can
paste it into Cursor / Claude Code / ChatGPT without leaving the
scan report. Also lands the EXP-4 top_action pin (cherry-picked
from the never-merged 2.2.0 chain).

### Added
- **fix_prompt rendering**: `Finding.fix_prompt: str | None` is
  populated from the rule's `fix_prompt:` YAML body with
  `{variable}` placeholders resolved against the same
  `context_probe` set as `action.template`. `_PromptDefaultingDict`
  + `_PROMPT_FALLBACKS` substitute a stack-agnostic phrase
  ("your test command", "your project's primary language", ...)
  when a probe didn't resolve, so the rendered prose stays readable
  on repos where no manifest was detected. `render_action` is
  untouched — Makefile bodies still want empty-string substitution
  for unresolved keys.
- **Top action pin** (EXP-4, cherry-picked): `scorer.compute_top_action`
  ranks findings by severity → pillar → weight → check_id and
  attaches the winner to `Report.top_action`. Both rich and plain
  renderers print a "Start here:" line above "Top friction".
  +13 tests in `tests/test_top_action.py`.

### Changed
- `renderers/terminal.py` prints the rendered `fix_prompt` line
  with `markup=False, highlight=False` so bracketed strings like
  `[project.scripts]` and `[tool.ruff]` render verbatim instead of
  being consumed as rich markup tags.
- Vendored rules pack refreshed from `agent-readiness-rules@v2.1.0`
  (was v1.5.0). All 38 rules now ship with authored `fix_prompt:`
  blocks. `manifest.toml`: `rules_version` 1 → 2,
  `pack_version` 1.5.0 → 2.1.0.

## [2.1.1] - 2026-05-04

### Fixed
- Relax `agent-readiness-insights-protocol` pin from `>=0.2,<1.0`
  to `>=0.1,<1.0`. The 0.2 floor was aspirational (protocol v0.2.0
  / v0.3.0 exist as git tags but were never published to PyPI),
  so `pip install agent-readiness==2.1.0` from a clean environment
  failed with `Could not find a version that satisfies the
  requirement agent-readiness-insights-protocol<1.0,>=0.2`. The
  engine only imports `Rule` for best-effort validation in
  `rules_eval/loader.py`; that import is wrapped in a try/except
  and degrades gracefully to a permissive `LoadedRule` path, so
  protocol v0.1.0 is sufficient. The next protocol release that
  actually lands on PyPI will let us re-tighten this pin in a
  future minor.

## [2.1.0] - 2026-05-04

The "action contract" release. Every `Finding` now carries an
agent-runnable command and a verify step, not just human-readable
prose. This was Phase 1 / EXP-1 of the rules-quality experiment
([rules_quality_research_plan.md][rqrp]) — D3 (agent-applicable)
recommendation coverage went from 0% to 100% on the v3 1000-repo
cohort.

[rqrp]: https://github.com/harrydaihaolin/agent-readiness-research/blob/main/research/rules_quality_research_plan.md

### Added
- **Action contract** ([#64]): `Finding.action` (`kind`, `command`,
  `path`, `template`, `preconditions`, `context_probe`) and
  `Finding.verify` (`command`, `description`) are first-class
  fields on every finding. Rules with `rules_version=2` populate
  these from their YAML; rules at `rules_version=1` continue to
  load and surface findings without action/verify, which preserves
  backwards compatibility for downstream scanners.
- **Context-probe instantiation** ([#64], EXP-3 in the experiment
  series): `{variable}` placeholders in `action.command` /
  `action.template` are resolved from probes at scan time.
  Example: `pnpm install --frozen-lockfile` is rendered with the
  actual package manager detected from the manifest, lockfile, and
  CI config — cross-validated by `Context Probe v2`. When no probe
  matches, the placeholder is replaced with the empty string so
  the printed line stays parseable rather than emitting a
  templated string an agent can't run.
- **Top-action pinning** (EXP-4): `Finding.top_action` is set
  deterministically per repo by the rule of severity → pillar
  order → weight, so consumers (the leaderboard, the public ROI
  view) can render "the one thing to fix next" without sorting
  themselves.
- `TRADEMARK.md` ([#67]): trademark policy reserving the
  `agent-readiness` and `ar` names, logos, and official surface
  names. Forks are MIT-allowed for code; rebrand or attribute
  per the policy. README "License" now points readers to both
  `LICENSE` and `TRADEMARK.md`.

### Changed
- `SUPPORTED_RULES_VERSIONS` now includes `2`. The loader keeps
  the old permissive path: a v0.3.0 protocol pin that rejects a
  rule for a missing `provenance:` field still falls through to
  `LoadedRule` so v1.5.0-vendored rules don't break the scan.
- Vendored rules pack stays at `agent-readiness-rules@v1.5.0`
  (38 checks). The next vendor refresh will pick up the v2.0.x
  pack with `provenance:` baked in (companion releases:
  `agent-readiness-insights-protocol` v0.3.0 +
  `agent-readiness-rules` v2.0.2).

### Notes for downstream
- `agent-readiness-leaderboard` and `agent-readiness-pro` should
  bump their pin to `agent-readiness>=2.1,<3` once they want the
  action contract surfaced in their scan output. Existing
  `>=1.4,<2` pins keep working until then; the wheel still
  ships the same 38-check vendored pack.
- JSON Report schema: `Finding` gains two new optional fields
  (`action`, `verify`). v1 consumers that ignore unknown fields
  stay compatible; consumers that hard-validate the schema
  should bump to schema v2.

[#64]: https://github.com/harrydaihaolin/agent-readiness/pull/64
[#67]: https://github.com/harrydaihaolin/agent-readiness/pull/67

## [1.5.0] - 2026-05-02

### Changed
- Vendored `agent-readiness-rules@v1.5.0`. The rules pack adds the new
  community-contributed `cognitive_load.readme_root_present` check
  (38 checks total, up from 37 in v1.4.0) and recalibrates the
  `repo_shape.large_files` thresholds (`threshold_lines` 500 → 1500,
  `threshold_bytes` 50 KB → 150 KB) to land its v3 cohort fire rate
  inside the 30–60% discriminative band. v3.1 had it firing at 88.1%,
  high enough that it had stopped discriminating; the recalibration is
  the one ideas-sweep change that ships in v1.5.0. The rest of the
  19-item v3.1 ideas backlog
  ([agent-readiness-research/research/ideas.archive.md](https://github.com/harrydaihaolin/agent-readiness-research/blob/main/research/ideas.archive.md))
  is closed out as deferred-with-rationale (engine matcher gap or
  research-grade gate per item).
- `MANIFEST.vendored_tag` bumped from `v1.4.0` to `v1.5.0`. Tarball
  SHA recorded in `src/agent_readiness/rules_pack/MANIFEST`.
- Reference fixtures regenerated against `agent-readiness-fixtures@v1.0.0`
  to reflect the new rule + the threshold change.

### Production gate
- The v3.2 release-snapshot run on the leaderboard's full 1000-repo
  cohort is the production confirmation gate. If `repo_shape.large_files`
  lands outside the 30–60% target band on v3.2, a v1.5.1 patch will
  tune thresholds further. Tracked under
  `agent-readiness-leaderboard/data/releases/scores_v3_1000_2026-05-XX.json`
  in the next snapshot release.

## [1.4.0] - 2026-05-02

### Added
- Vendored `agent-readiness-rules@v1.4.0` rules pack (37 checks,
  up from 7 in v1.0.0). New checks span all four pillars and unlock
  the v3 article cohort: `headless.unrunnable_e2e`,
  `workflow.concurrency_guard`, `agent_docs.ci_feedback_loop`,
  `deploy.smoke_check`, plus refinements to existing
  `cognitive_load`, `feedback`, `flow`, and `safety` rules. The
  rules pack is the version cited by the v3 1000-repo article.
- `--list-rules` (planned 1.5) is **not** in this release; downstream
  consumers continue to read `MANIFEST.vendored_tag` + count
  `*.yaml` to discover pack version + check count (see
  `agent-readiness-leaderboard/scripts/scan.py:_scanner_meta`).

### Changed
- `MANIFEST.vendored_tag` bumped from `v1.0.0` to `v1.4.0`.
  `verify-vendoring` CI gate confirms the pack matches the
  upstream tag's tarball SHA.

### Notes for downstream
- `agent-readiness-leaderboard` should pin
  `agent-readiness>=1.4.0,<2`. Existing v1.0.0 cohort snapshots
  remain valid for replay; the v3 article reruns under `v1.4.0`
  will be filed as `scores_v3_*.v140.json` alongside the
  preserved `*.v100.json`.
- `agent-readiness-pro` already vendored the same rule set ahead
  of this release; no further pin work needed there.

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

[Unreleased]: https://github.com/harrydaihaolin/agent-readiness/compare/v2.1.1...HEAD
[2.1.1]: https://github.com/harrydaihaolin/agent-readiness/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v1.5.0...v2.1.0
[1.5.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v1.1.0...v1.4.0
[1.1.0]: https://github.com/harrydaihaolin/agent-readiness/compare/v1.0.0...v1.1.0
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
