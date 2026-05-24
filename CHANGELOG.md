# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)

## [Unreleased]

## [2.9.0] - 2026-05-23

Minor: closes a recurring false-positive class — *"this is obviously
a monorepo but agent-readiness sees a single Python project."*

The old detector only knew about JS-ecosystem tooling
(`npm workspaces`, `lerna`, `pnpm`, `nx`, `rush`, `turborepo`).
Real-world enterprise monorepos that pre-date `uv` / `rye` workspace
declarations — typically N sibling Python packages stitched together
by a top-level Earthfile / Bazel / Jenkinsfile — were misclassified
as single repos, which silently suppressed every monorepo-aware
heuristic downstream.

### Added

- **`RepoContext.monorepo_tools`** now also reports:
  - `uv-workspace` — `[tool.uv.workspace]` in `pyproject.toml`
  - `rye-workspace` — `[tool.rye.workspace]` in `pyproject.toml`
  - `cargo-workspace` — `[workspace]` in `Cargo.toml`
  - `gradle-multi-project` — `settings.gradle` or `settings.gradle.kts`
  - `convention-monorepo` — ≥ 2 *direct child* directories each
    carrying their own manifest (`pyproject.toml` / `setup.py` /
    `Cargo.toml` / `package.json` / `go.mod` / `build.gradle` /
    `pom.xml`). Depth-1 only so an `examples/foo/setup.py` next to
    the real root can't trip the heuristic.
- **`enumerate._detect_manifest_signals`** gains a matching
  `convention_monorepo: bool` so the workspace-scan fast-path and
  per-repo scan path agree.
- 13 new tests in `tests/test_monorepo_detection.py` covering each
  new signal, the depth-1 / excluded-dirs / threshold guardrails, and
  a single-package regression check.

### Fixed

- Enterprise Python monorepos with N sibling packages and a root
  `pyproject.toml` that only configures ruff/isort (no
  `[project]` block, no workspace declaration) now correctly report
  `is_monorepo: True` and surface in the scan's context envelope as
  `monorepo_tools: ["convention-monorepo"]`. The same shape covers
  Earthfile / Bazel / Jenkinsfile-orchestrated layouts.

## [2.8.0] - 2026-05-23

Minor: ships the **`applies_when` rule selector** — rules can now
declare which repos they apply to and short-circuit to
`not_measured` on the rest, so YAML-only / docs-only / config-only
repos stop taking score hits from code-ecosystem rules that don't
apply to them.

Closes [#87](https://github.com/harrydaihaolin/agent-readiness/issues/87).
Unblocks
[agent-readiness-rules#28](https://github.com/harrydaihaolin/agent-readiness-rules/issues/28).

### Added

- **`src/agent_readiness/rules_eval/applies_when.py`** — new module:
  - `rule_applies(applies_when, ctx) -> bool` — AND-combine
    predicates against `RepoContext`. Empty/None means "always
    applies" (backwards-compatible).
  - Two v1 predicates:
    - `any_language_detected: bool` — true iff
      `ctx.detected_languages` is non-empty. Use to opt rules out
      of YAML/docs/config-only repos.
    - `languages_in: list[str]` — true iff any detected language
      appears in the list (case-insensitive). Use for
      ecosystem-specific rules.
  - Unknown predicate keys evaluate to `False` and log a warning
    (closed-world: a rule pack pinned ahead of the engine cannot
    silently enable new predicates the engine doesn't yet know).
- `LoadedRule.applies_when: dict | None` carried through the loader.
- 14 new tests in `tests/test_applies_when.py` covering predicate
  dispatch, AND-combination, case-insensitivity, unknown-key safety,
  loader extraction, and evaluator integration.

### Changed

- **`rules_eval/evaluator.py`** — `evaluate_rule()` now consults
  `rule.applies_when` before calling the matcher. An excluded rule
  returns the same `not_measured=True` shape as the existing
  unknown-match-type fallback, so the scorer drops it from the
  weighted average instead of treating absent findings as a perfect
  score.

### Notes

This is purely additive at the rule-schema level: rules that don't
declare `applies_when` behave identically to before. The companion
rules-pack change ([agent-readiness-rules#28](https://github.com/harrydaihaolin/agent-readiness-rules/issues/28))
will add `applies_when: {any_language_detected: true}` to the three
known-FP rules: `manifest.detected`, `manifest.lockfile_present`,
`entry_points.detected`.

## [2.7.0] - 2026-05-23

Minor: ships **workspace-starter M1** — the scanner can now load and
validate the v1 manifest format (workspace bible: `manifest.yaml`,
`glossary.yaml`, `boundaries.yaml`, `rules/*.yaml`,
`.agent-readiness-version`). New `agent-readiness manifest validate`
CLI subcommand emits a stable `ManifestValidationResult` JSON envelope
that the MCP `manifest_validate` tool serializes byte-for-byte.

### Added

- **`src/agent_readiness/manifest/`** — new package:
  - `loader.py`: `load_manifest_dir(path) -> LoadedManifest` parses the
    standard manifest directory layout into typed Pydantic models from
    `agent-readiness-insights-protocol>=0.5.0`. Raises
    `ManifestLoadError` (with `location`) on missing files, YAML parse
    failures, or schema violations.
  - `validator.py`: `validate_manifest_dir(path) -> ValidationResult`
    layers two semantic checks over the schema:
    1. boundary rules may only reference tag axes declared in
       `boundaries.spec.tagAxes`;
    2. arch rule `metadata.id` must share the numeric prefix of its
       containing filename (e.g. `001-foo.yaml` ⇒ id starts `001-`).
    Emits a `to_json_envelope()` shape that's the contract for the
    MCP tool and any future renderers.
- **`agent-readiness manifest validate <path>`** CLI subcommand:
  human and `--json` output; `--strict` upgrades warnings to exit 1;
  exit 2 on missing/invalid path.
- 16 new tests in `tests/manifest/` (6 loader, 6 validator, 4 CLI).

### Changed

- **`pyproject.toml`** — pin `agent-readiness-insights-protocol` to
  `>=0.5.0,<0.6.0` (was `>=0.1,<1.0`). Required for the new manifest
  models; the upper bound matches the protocol-package SemVer policy.

### Notes

This is M1 of the workspace-starter superpower (see
`agent-readiness-research/docs/superpowers/plans/2026-05-22-workspace-starter-plan.md`).
M2–M6 (materialize / add-repo / boundaries-check / glossary / sessions)
land in future minor bumps.

## [2.6.0] - 2026-05-23

Minor: ships **workspace-aware scanning** with a new **Coordination
pillar** (workspace-only). Adds two CLI subcommands (`enumerate` and
`workspace-scan`) and the library functions that back them, so the
MCP server and skill can drive the new "enumerate → classify → scan"
flow without re-implementing classification heuristics.

### Added

- **`src/agent_readiness/enumerate.py`** — new module:
  `enumerate_workspace(path) -> EnumerationReport`. Static depth-1
  enumeration of a directory's direct children. Detects `.git` or
  `README.md` as qualifiers, applies a standard ignore list, collects
  per-child language hints from top-level manifests, and exposes
  monorepo-tooling signals (pnpm, cargo, pyproject, package.json,
  gradle) for downstream classifiers.
- **`src/agent_readiness/coordination.py`** — new module: the v1
  Coordination pack with three workspace-only checks:
  - `coordination.root_agents_md` — workspace root has a non-empty
    AGENTS.md (portfolio-level orientation).
  - `coordination.repos_manifest` — workspace declares its member
    repos (pnpm-workspace, cargo workspace, go.work, package.json
    workspaces, repos.yaml, or AGENTS.md enumeration).
  - `coordination.dep_graph` — workspace documents dependency / change
    order (per Mabl & Bishoy Labib, the single most critical concept
    for coherent multi-repo agent work).
- **`src/agent_readiness/workspace_scan.py`** — new module:
  `scan(path, children) -> WorkspaceReadinessReport`. Runs the
  Coordination pack at the root, runs the existing per-repo scan on
  each child, aggregates per-pillar means, and picks a `top_action`
  whose `scope` is `"workspace"` (Coordination beats child) or
  `"child"` (the worst child's `top_action` promoted with `child_path`
  stamped on).
- **`agent-readiness enumerate <path>`** — new CLI subcommand.
  Emits the static enumeration envelope. `--json` for the wire
  envelope; default output is a human-readable summary. Exit code 0
  on success, 2 on missing path / non-directory.
- **`agent-readiness workspace-scan <path> --children=...`** — new
  CLI subcommand. Wraps `workspace_scan.scan()` with a comma-separated
  `--children` list. Exit 0 on success, 2 on missing path or any
  child path, 3 on empty `--children`.
- **`Pillar.COORDINATION`** — new enum value in `models.Pillar`.
  Per-repo scoring excludes it (workspace-only); the workspace scan
  carries it explicitly with `source: "workspace"` in the envelope.
- **`ChildReadiness`, `EnumerationReport`, `WorkspaceReadinessReport`,
  `ChildEnumeration`** — new dataclasses in `models.py`. Round-trip
  tested with stable `to_dict()` envelopes.
- **`tests/test_enumerate.py`**, **`tests/test_coordination.py`**,
  **`tests/test_workspace_scan.py`**, **`tests/test_cli_enumerate.py`**,
  **`tests/test_cli_workspace_scan.py`**, **`tests/test_models_workspace.py`**
  — 37 new unit + integration tests covering the new surfaces.

### Changed

- `scorer.score()` skips `Pillar.COORDINATION` when assembling per-repo
  pillar lists; the terminal renderer and per-repo `Report` consumers
  continue to operate on the four legacy pillars.
- `scorer._PILLAR_PRIORITY` extended with `Pillar.COORDINATION: 4` so
  the per-finding lookup in `compute_top_action` is exhaustive over
  the enum and never `KeyError`s if a test rig constructs a
  Coordination Finding in per-repo context.

## [2.5.0] - 2026-05-21

Minor: ships **workspace detection** as a first-class scanner concern,
exposed via a new `agent-readiness detect <path>` CLI subcommand and
consumed by the MCP server (next release) and the skill.

The detector classifies a path as one of `single_repo` / `monorepo` /
`multi_repo_workspace` and returns the wire-stable `detect_v1` envelope
(repos list, AGENTS.md enrichment + drift warnings, signals fired).

This release also adds a **breaking** behavior change: `agent-readiness
scan <path>` now exits non-zero with a structured error when `<path>` is
a multi-repo workspace (a parent directory containing multiple sibling
`.git/`'d repos). Today's behavior on those paths was to silently score
the parent as if it were one repo, producing garbage numbers. The error
points at `agent-readiness detect <path>` so the user can pick the
right repo and re-run. Callers that were piping `scan` on workspace
roots will need to update; everyone else is unaffected.

### Added

- **`src/agent_readiness/workspace_detect.py`** — new module: `detect(path)
  -> WorkspaceDetection`. Classifies single repos via three signals
  (explicit workspace declaration, convention dir + child manifests,
  manifest density), multi-repo workspaces via one-level child `.git/`
  walking, and falls back to manifest-density when no `.git` is present
  anywhere. Parses `AGENTS.md` tables (this very workspace's format) for
  display-name enrichment + drift warnings.
- **`agent-readiness detect <path>`** — new CLI subcommand. Default
  output is a human-readable summary; `--json` emits the structured
  envelope; `--quiet` suppresses the summary for clean piping. Exit code
  0 for any resolved classification, 2 for input errors.
- **`tests/test_workspace_detect.py`** — 43-test suite covering every
  Signal A manifest, Signal B convention dirs, Signal C density,
  step-2 multi-repo walking, step-3 no-git fallback, AGENTS.md
  enrichment + both drift kinds, and a dogfood test that the
  agent-readiness checkout itself classifies as `single_repo`.

### Changed

- **`agent-readiness scan <path>`** — now calls `detect()` first. On
  `multi_repo_workspace` classification, exits 2 with a structured JSON
  error on stderr (`{"error": "multi_repo_workspace", "hint": ..., "detected_repos": [...], "root": ..., "version": "detect_v1"}`). This
  is the breaking change called out above.

### Wire format

`detect_v1` — bump this string when the envelope shape changes; the MCP
server and skill check it before parsing.

## [2.4.6] - 2026-05-21

Vendor-only release. Picks up `agent-readiness-rules` v2.4.1 so the
default scan (no `--rules-dir` flag) actually uses the new
`secret_scanning_config` matcher that v2.4.5 added. Without this
vendor bump, fresh installs of v2.4.5 ship the new matcher but the
bundled YAML still says `match.type: path_glob`, so the
precondition gate does nothing on default scans.

### Changed

- **`src/agent_readiness/rules_pack/`** vendored from
  [`agent-readiness-rules` v2.4.1](https://github.com/harrydaihaolin/agent-readiness-rules/releases/tag/v2.4.1).
  The only meaningful diff is
  `safety/safety.gitleaks_config.yaml` flipping `match.type` from
  `path_glob` to `secret_scanning_config`.

### Verified

Smoke-tested on a pure-library Scala fixture (no env reads, no
cloud SDKs, no `.env`, no hardcoded credentials):

```
safety.gitleaks_config  score=100.0  warn/err findings=0
```

Before this vendor bump the same fixture under v2.4.5 fired with
`score=80`. The default scan now matches the unit-test behaviour.

## [2.4.5] - 2026-05-21

The "`safety.gitleaks_config` shouldn't fire on pure-library repos"
follow-up. v2.4.4 closed the `gitignore_coverage` regression flagged
by the 2026-05-21 calibration cycle; this release works on the
*next* FP target surfaced in the same cycle's residue list:
`safety.gitleaks_config` was firing at 64.9 % top-finding rate on
the v3 cohort and at 67.4 % (rising) on the n=97 language-stratified
sample, including JVM library repos with zero credential-handling
surface area. The Scala-repo complaint from the user's
`mle-authn-sidecar` report was the canonical case.

### Why

The original rule was a plain `path_glob` — fire when none of a list
of well-known secret-scanning configs exists. That works on Python
web apps where every repo touches `os.environ`, but punishes JVM
numerics packages, OCaml type-system playgrounds, and pure-library
repos that have no credentials to leak. There was no notion of
*whether the repo even handles secrets*.

### Added

- **`rules_eval/private_matchers/secret_scanning_config.py`** —
  new matcher type. Two-stage check:
  1. **Accept**: if any of the rule's `accept_paths` exists, pass.
  2. **Precondition**: if no accept path exists *and* the repo
     shows evidence of handling secrets, fire with a message that
     names the evidence so the user can see *why* the rule applies
     to their repo. Evidence comes in four channels:
     - **Env files**: `.env`, `.env.<env>`, `.envrc` at any path.
     - **Env-var reads** in source: `os.environ`, `os.getenv`,
       `process.env.*`, `System.getenv`, `os.Getenv`,
       `std::env::var`, `ENV[`, `getenv()`, `Sys.getenv`,
       `Config.fetch :env`, `dotenv!`, `dotenv` library imports.
     - **Cloud SDK imports**: boto3 / aws-sdk / @aws-sdk/*,
       google.cloud / @google-cloud/*, azure.identity / @azure/identity,
       firebase-admin, stripe, twilio, hvac (Vault), database URLs.
     - **Compose / IaC**: docker-compose `secrets:` / `env_file:`,
       kubernetes `kind: Secret`, terraform
       `aws_secretsmanager_secret` / `google_secret_manager_secret`
       / `azurerm_key_vault_secret` / `vault_generic_secret`, helm
       `.Values.*Secret`.
     - **Hardcoded credentials** (mirrors `secrets.basic_scan` so the
       two rules stay aligned): AWS access keys (`AKIA[A-Z0-9]{16}`),
       GitHub tokens (`gh[pousr]_…`), Slack tokens (`xox[abprs]-…`),
       Google API keys (`AIza[A-Za-z0-9_-]{35}`), Stripe live keys
       (`sk_live_…`/`pk_live_…`), PEM private key headers.
  3. **Skip silently** when no accept path exists *and* there's no
     secret-handling surface area — the FP suppression that closes
     the user's original complaint.
  The matcher is scoped (`max_files_scanned=200`,
  `max_bytes_per_file=64000`) so a chatty monorepo doesn't blow the
  scan budget. `require_precondition: false` degrades the matcher
  to plain accept-path-presence for downstream packs that want
  v1.5.0 semantics back.

### Changed

- **`safety.gitleaks_config`** (in `agent-readiness-rules`) — match
  type flipped from `path_glob` to `secret_scanning_config`. Rule
  text + `fix_prompt` updated to tell the user *why* the rule fired
  (which evidence channel triggered it) and that pure-library repos
  are auto-skipped.

### Evidence

- **Snapshot regen**: the four `agent-readiness-fixtures` snapshots
  re-rendered cleanly under the new matcher. `good` and `broken`
  continue to fire (env-file evidence and hardcoded AWS-key
  evidence respectively); `noisy` and `monorepo` correctly *stop*
  firing because they have no secret-handling surface area — they
  were FPs under v1.5.0 / v2.4.4.
- **Tests**: 11 new behavioural cases in
  `tests/test_private_matchers.py::TestSecretScanningConfig`
  (accept-path pass, no-evidence skip, env-var read, dotenv file,
  cloud SDK import, compose `env_file:` block, terraform secret
  resource, hardcoded AWS key, JVM repo *with* env reads still
  fires, `require_precondition: false` degradation, missing-config
  defensive skip). Full suite: 183 passed, 1 skipped (no
  regression from the new matcher).
- **AAIF evidence companion**:
  `agent-readiness-research/research/aaif_evidence/2026-05-21_calibration_cycle.md`
  (follow-up #1 in the residue list).
- **Cohort guard**: `agent-readiness-leaderboard/data/cohorts/jvm_skewed_v1.json`
  (PR #27) — 144 repos across 12 languages, will be used to
  measure `safety.gitleaks_config` clearance in the next
  calibration cycle.

## [2.4.4] - 2026-05-21

The "language-aware gitignore matcher shouldn't tighten the bar"
hotfix. v2.4.3 shipped `language_aware: true` for
`gitignore.covers_junk`, which narrowed the *requested* group set to
universals + detected-language groups — but inadvertently switched the
threshold semantics from "7-of-13 groups required" (v1.5.0 default) to
"every filtered group required" (v2.4.3 strict). A Python repo that
covered six of the now-seven required groups but lacked a
`htmlcov/` / `.coverage` pattern silently flipped from passing into a
finding. The 2026-05-21 calibration cycle measured this as a **+4.1 pp
regression** on the full 1000-repo v3 cohort
([daily-scan 26209874024](https://github.com/harrydaihaolin/agent-readiness-leaderboard/actions/runs/26209874024)),
exactly the kind of footgun the language-aware mode was supposed to
*prevent*.

### Why

The cycle started as a council-reviewed plan
([`.council/self-improvement-2026-05-21/PLAN.md`](https://github.com/harrydaihaolin/agent-readiness-research/blob/self-improvement/cohort-fp-fn-2026-05-21/.council/self-improvement-2026-05-21/PLAN.md)
in `agent-readiness-research`) with two pre-declared targets we
expected v2.4.0 to clear by ≥ 5 pp:
`safety.gitignore.covers_junk` and `feedback.manifest.detected`. The
n=97 language-stratified paired sample showed both flat — but the
parallel full-cohort daily scan, which we don't normally watch in the
same loop, showed `gitignore.covers_junk` going the *wrong* direction.
Reading the matcher revealed the threshold tightening that the YAML
config never asked for.

### Fixed

- **`rules_eval/private_matchers/gitignore_coverage.py`** —
  `language_aware: true` now uses an explicit two-stage check
  ("all universal groups required; one language-group miss allowed
  when the ecosystem has ≥ 3 language-specific groups in scope")
  instead of "every effective_requested group required". Python /
  TypeScript / JavaScript repos missing only `coverage` /
  `python_egg_info` / equivalents stop firing; Rust / Scala /
  Clojure repos (smaller language-group sets) stay strict so the
  language signal isn't silently waived. Unclassifiable repos keep
  the v1.5.0 fallback unchanged.
- **`tests/test_private_matchers.py`** — three new regression tests
  cover the Python "missing only coverage" case, the universal-miss
  case (always fires), and the Rust single-language-group case (still
  strict). All 47 matcher tests + the full 172-test suite green.

### Evidence

- [`agent-readiness-research`/`research/aaif_evidence/2026-05-21_calibration_cycle.md`](https://github.com/harrydaihaolin/agent-readiness-research/blob/self-improvement/cohort-fp-fn-2026-05-21/research/aaif_evidence/2026-05-21_calibration_cycle.md)
  — full Phase-1 (TFR bands over 993 v3 repos), Phase-2 (n=97 paired
  diff), Phase-3 (LLM-judge: **D1 0.44 → 1.00, D2 0.44 → 1.00,
  D3 0.38 → 0.72** — the actionability rewrites are working) and
  Phase-4 (this fix) artefacts. Designed to feed the next AAIF
  qualification cycle.
- The pre-declared targets failing to clear on the v3 cohort is
  itself a finding: the v3 cohort is GitHub-topic-seeded and
  under-represents the JVM / Clojure / Erlang / OCaml / Julia / R
  population the v2.4.3 fix targets (zero Scala, 1 Clojure, 1 Julia
  in 993 repos). Building a JVM-skewed cohort is queued as a
  follow-up research item.

## [2.4.3] - 2026-05-21

The "stop score-chasing the wrong ecosystem" release. Engine-side
gains a language-aware mode on the gitignore-coverage matcher, a
broader manifest list (Scala / Clojure / Erlang / OCaml / Julia / R /
Perl / Haskell now recognised by their canonical manifest), and a
scaffolder that substitutes the *actual* canonical commands for the
detected language into the AGENTS.md template. Re-vendors the
upstream rule pack to **v2.4.0**, which flips the new behaviour on
at the YAML layer.

### Why

A clean Scala / SBT repo scanned at v2.4.2 hit overall 75 / 100
with pillar scores of 94 / 92 / 93 / 96 — by any honest read this
is a healthy repo. The safety pillar dipped to 95.7 because
`gitignore.covers_junk` fired with *"missing python_pycache,
node_modules, dist_build, go_vendor, python_egg_info, coverage,
terraform"* — every missing group except `coverage` is an
ecosystem the repo doesn't use. The action was *"add seven
ecosystems' worth of patterns to your `.gitignore`"* — pure
score-chasing. Same repo also hit `manifest.detected` despite
`build.sbt` being present at the root, because the engine's
`_ROOT_MANIFESTS` tuple lagged the language-detection table.

Same root cause in both: the matchers were Python / JS / Go first
with hard-coded ecosystem checklists, while the engine's *prose*
(rule explanations, fix_prompt bodies, language tables) already
knew about every supported ecosystem. v2.4.3 brings the enforcement
in line with the prose.

### Added (engine)

- `gitignore_coverage`: new `language_aware: true` config flag.
  When set, the matcher resolves the repo's primary language via
  the existing `context_probe._detect_primary_language` probe and
  filters the requested group list down to *universal* groups
  (`dotenv` / `ide_junk` / `logs`) plus the per-language groups
  for each detected language. Multi-language repos require the
  *union*. Unclassifiable repos fall back to the full-list
  behaviour so we don't silently under-fire on unknown ecosystems.
- `manifest_introspection`: `_ROOT_MANIFESTS` grown from 16 → 30
  entries to mirror `context_probe._LANGUAGE_BY_MANIFEST`. Now
  recognises `build.sbt`, `build.sc` (Mill), `project.clj`,
  `deps.edn`, `rebar.config`, `dune-project`, `Project.toml`
  (Julia), `DESCRIPTION` (R), `Makefile.PL` + `cpanfile` (Perl),
  `Pipfile`, `tsconfig.json`. `_MONOREPO_MANIFESTS` grows
  similarly so Scala / Java / Clojure monorepos with modules at
  `modules/<name>/build.sbt` are recognised at depth==2.
- `scaffold._substitute()` now runs the same probe stack as rule
  actions and substitutes `{{PRIMARY_LANGUAGE}}`,
  `{{INSTALL_COMMAND}}`, `{{TEST_COMMAND}}`, `{{LINT_COMMAND}}`
  into bundled templates. The shipped `AGENTS.md` template now
  carries those tokens; a Scala repo's freshly-scaffolded
  AGENTS.md now ships `sbt compile` / `sbt test` /
  `sbt scalafmtCheckAll` in the Quick Start block instead of
  `<replace with your install command>` placeholders. Falls back
  to readable English (`your install command`) when the probe
  can't resolve.
- `agent_docs.canonical` added to `_CHECK_TEMPLATES` so the
  scaffolder seeds AGENTS.md whether the firing rule is the
  warn-level canonical rule or the softer
  `agent_docs.present` info rule.

### Changed (vendored rules)

- Re-vendored `agent-readiness-rules` from **v2.3.0 → v2.4.0**
  (`scripts/vendor_rules.sh v2.4.0`). Three rule changes:
  - `gitignore.covers_junk`: `match.language_aware: true`.
    Explanation, fix_hint, fix_template content, fix_prompt, and
    verify.command all rewritten in the per-language voice.
  - `manifest.detected`: verify.command extended to mirror the
    engine's new manifest list.
  - `agent_docs.canonical`: `action.template` rewritten to
    interpolate `{primary_language}` /
    `{language_install_command}` / `{language_test_command}` /
    `{language_lint_command}` into the AGENTS.md content; the
    `context_probe` block grows to include `primary_manifest`
    and `package_manager` so the rendered prose has the full
    ecosystem context.

### Validation

- `python3 -m pytest -q`: **169 passed, 1 skipped** (was 156 / 1).
  13 new tests: 4 language-aware gitignore (Scala-clean /
  Scala-missing-dotenv / Python-Node monorepo / unclassifiable
  fallback), 3 broader-manifest (build.sbt / deps.edn /
  Project.toml), 6 scaffolder (substitution paths +
  `agent_docs.canonical` mapping).
- `manifest.toml` `pack_version` is `"2.4.0"` post-vendor.
- `MANIFEST` records the v2.4.0 tarball SHA.

### Expected field impact

A clean Scala / SBT repo with no Python or Node should now score
~93 instead of 75 — the gitignore false-fire and the missing-
manifest false-fire both clear. `apply_top_action` on a fresh
repo writes an AGENTS.md with the actual canonical commands
instead of a generic skeleton.

### Cross-repo provenance

- Engine PR: [#78](https://github.com/harrydaihaolin/agent-readiness/pull/78).
- Rules-pack PR: [agent-readiness-rules#26](https://github.com/harrydaihaolin/agent-readiness-rules/pull/26).
- Council follow-on: backlog item *"rules engine prompt
  generation isn't language agnostic enough"* (Phase 1; see
  `agent-readiness-research/research/triage_2026-05-20_followups.md`).

## [2.4.2] - 2026-05-21

The "agent-led explanations land in the prompts" release. Re-vendors
the upstream rule pack so every `explanation` field — and therefore
the lede sentence of every `fix_prompt` an agent reads — leads with
the agent consequence, not the abstract code-quality framing. Zero
engine code changes; this is a pure rules-pack refresh.

### Changed (vendored rules)

- Re-vendored `agent-readiness-rules` from **v2.2.0 → v2.3.0**
  (`scripts/vendor_rules.sh v2.3.0`). Highlights of the upstream change:
  - 23 of 38 rules had their `explanation` lede rewritten so the
    first sentence answers "what does the agent lose if this is
    ignored?" instead of describing the abstract code/config state.
    Mirrors the existing `Without this, an agent...` openers on
    `fix_prompt` and gives the two fields a single voice.
  - The other 15 rules already led with agent / "an agent" prose
    and are byte-identical post-rewrite.
  - **No schema change.** `action`, `verify`, `fix_prompt`,
    `match`, and `context_probe` are byte-identical on every rule.
    A reviewer reading `git diff src/agent_readiness/rules_pack/`
    sees only `explanation` text changes plus the bumped
    `pack_version` (2.2.0 → 2.3.0) in `manifest.toml`.

### Why

Before v2.3.0, `agent-readiness scan --json` could ship two paragraphs
of friction text whose *frame* disagreed: the structured `explanation`
treated the rule as an abstract code-quality concern ("High cyclomatic
complexity means many independent control-flow paths..."), while
`fix_prompt` led with the agent consequence ("Without this, an agent
editing a high-CC function has to reason across every branch..."). An
agent (or a human) reading the scan output had to mentally reconcile
the two voices. v2.3.0 settles on the agent-led voice for both fields,
so the explanation now reads as the start of the same paragraph the
`fix_prompt` finishes.

This is the *copy* half of the COPY-O3 protocol (council 2026-05-20
verdict on the legacy `EXP-1` backlog item, renamed in the same pass
to clear an id collision with the shipped action contract). The
*measurement* half — an `O3` LLM-judge run that grades the explanation
field in isolation against an 0.80 YES-rate gate — ships in
`agent-readiness-research/scripts/evaluate_actionability.py
--objective explanation`; that gate is inert until an operator with a
`GEMINI_API_KEY` produces both a v2.2.0 baseline and a v2.3.0
post-rewrite measurement (`data/exp_o3_baseline.json` scaffold ships
the reproduction commands).

### Validation

- `python3 -m pytest -q`: 156 passed, 1 skipped (no regression from
  the vendored rules pack).
- `scripts/vendor_rules.sh v2.3.0` writes a tarball SHA into
  `src/agent_readiness/rules_pack/MANIFEST` (audit trail; confirms
  the bytes match the released tag, not a 404 page).
- `src/agent_readiness/rules_pack/manifest.toml` `pack_version` is
  `"2.3.0"` post-vendor.

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
