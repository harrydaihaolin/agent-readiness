#!/usr/bin/env python3
"""Pre-build check: fail if ``_dashboard_dist`` is missing or empty."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    dist = Path(__file__).parent.parent / "src/agent_readiness/_dashboard_dist"
    index = dist / "index.html"
    if not index.exists():
        print(
            f"FAIL: {index} missing — run `make dashboard` first.",
            file=sys.stderr,
        )
        return 1
    files = list(dist.rglob("*"))
    print(f"OK: dashboard dist present at {dist} ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
