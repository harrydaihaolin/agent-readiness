# Claude Code guide

Conventions specific to Claude Code working in this repository.
For general agent conventions see [`AGENTS.md`](./AGENTS.md).

## Quick start

```bash
make dev        # install dev deps (pip install -e ".[dev]")
make test       # run tests (unittest discover, no pytest required)
make lint       # ruff check src tests
PYTHONPATH=src python3 -m agent_readiness.cli scan .   # dogfood the tool on itself
```

## Key invariants

- **Dogfood on every iteration.** Run `PYTHONPATH=src python3 -m agent_readiness.cli scan .`
  after each change. The score should not regress. Fix friction before moving on.
- **Headless-first.** The CLI has no interactive prompts. `--json` output is stable
  (schema-versioned). Exit codes mean things. Do not break these contracts.
- **Static checks only in Phase 1–3.** Checks that execute repo code are gated behind
  `--run` and run inside Docker. Never shell out to target-repo code from a static check.

## Adding a check (summary)

1. `src/agent_readiness/checks/<name>.py` — `@register(...)` decorated function returning `CheckResult`
2. Import it inside `_ensure_loaded()` in `src/agent_readiness/checks/__init__.py`
3. Update `RUBRIC.md` and `PLAN.md` (check must have a name-able agent failure mode)
4. Add or extend a fixture; update snapshot assertions if scores shift

## Do-not-touch without a reason

- Default pillar weights in `scorer.py` — changing these shifts every reported score
- `Report.schema` integer in `models.py` — bump only on intentional breaking changes
- Sandbox contracts in `sandbox.py` — hard rules live in `SANDBOX.md`

## Commit and branch conventions

- Feature branches: `feat/<short-description>`
- Conventional Commits style where reasonable
- Run `make lint && make test` before committing
