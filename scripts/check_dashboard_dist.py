#!/usr/bin/env python3
"""Pre-build check: fail if ``_dashboard_dist`` is missing, empty, or stale.

"Stale" means the bundled SPA is missing a route the engine actively hands
out (e.g. the onboarding wizard) — see
``agent_readiness.dashboard_dist_check`` for the shared logic, which the
test suite also enforces.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_readiness.dashboard_dist_check import find_dist_problems  # noqa: E402


def main() -> int:
    dist = Path(__file__).parent.parent / "src/agent_readiness/_dashboard_dist"
    problems = find_dist_problems(dist)
    if problems:
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        return 1
    files = list(dist.rglob("*"))
    print(f"OK: dashboard dist present and fresh at {dist} ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
