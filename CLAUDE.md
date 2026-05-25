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

## live_scan package — invariants

- **POSIX-only.** Windows support is a deliberate non-goal in v1.
- **Atomic writes.** Any JSON the dashboard might be polling MUST go through
  `live_scan.envelope.atomic_write_json`. Direct writes are a bug.
- **PID stamping.** `daemon.pid` is JSON with `{pid, started_at, scan_id}`.
  Before any SIGTERM, verify all three via `pidfile.verify_pidfile` →
  `PidStatus.LIVE`. PID-recycle on dev laptops is a real risk; do not
  skip this check.
- **`server.url` file is the MCP wire protocol.** When the HTTP server is
  ready, the CLI atomically writes `<scan-dir>/server.url`. MCP polls
  for that file. Stdout is free for normal click output — DO NOT
  re-introduce a stdout contract.
- **Hard scan timeout.** 60 minutes default via `AGENT_READINESS_SCAN_TIMEOUT_S`.
  The worker self-kills past this; no zombie daemons.
- **Sequential v1.** Spec 2 lifts to parallel. When you add parallelism,
  the envelope's `progress.in_flight` field (already a list) accommodates
  N concurrent in-flight paths.
- **`_dashboard_dist/` is generated.** Don't hand-edit. Refresh with
  `make dashboard` (which builds the analytics-dashboard repo and copies
  `dist/`). Wheels never ship without it — see
  `scripts/check_dashboard_dist.py`.
