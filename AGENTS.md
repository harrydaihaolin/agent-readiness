# Agent guide

Conventions for AI coding agents working in this repository.

## Canonical commands

- Install dev deps: `make dev`
- Run tests:        `make test`
- Lint:             `make lint`
- Run the CLI:      `PYTHONPATH=src python3 -m agent_readiness.cli scan .`
  (or `agent-readiness scan .` after `make install`)

The tool itself is fully headless: stable JSON via `--json`, tab-separated
`list-checks`, prose `explain <check_id>`, and exit codes that mean
things. There are no required interactive prompts.

## Source of truth

- [`RUBRIC.md`](./RUBRIC.md) — what we benchmark and why. Every check
  must justify itself against the pillars and the headless-first
  principle here.
- [`SANDBOX.md`](./SANDBOX.md) — Docker execution model for `--run`
  (Phase 2). Devcontainer-first, hard fail on docker-native repos,
  no host-execution fallback.
- [`PLAN.md`](./PLAN.md) — phased roadmap.

If a behaviour is in the code but not in these three docs, the docs are
the bug.

## Adding a check

1. Create a module under `src/agent_readiness/checks/`.
2. Define a function decorated with `@register(...)` returning a
   `CheckResult`.
3. Import the new module from `src/agent_readiness/checks/__init__.py`
   inside `_ensure_loaded`.
4. Update `RUBRIC.md` and `PLAN.md` so the check has a name-able line
   to an agent failure mode (the discipline that keeps us out of
   linter creep).
5. Add or extend a fixture so the check actually fires; update
   `tests/test_phase1.py` snapshots if expected scores shift.

## Do-not-touch (without a clear reason)

- Default pillar weights in `src/agent_readiness/scorer.py`.
  Changing these moves every reported score; coordinate with a
  rubric update.
- The JSON `schema` integer in `models.Report`. Bump only on
  intentional breaking changes; downstream consumers will pin.
- `src/agent_readiness/sandbox.py` contracts (preflight, no host
  fallback, two-phase execution). The hard rules live in SANDBOX.md.

## Style

- Stdlib + click + (optional) rich. No pydantic, no typer, no heavy
  static-analysis libs in Phase 1 — those land per-phase as needed.
- Type-annotated, `from __future__ import annotations` at the top of
  modules.
- Conservative regex/heuristic checks: false positives erode trust
  faster than false negatives.

## Branch + commit conventions

- Feature branches: `feat/<short-description>`
- Conventional Commits style for messages where reasonable.
