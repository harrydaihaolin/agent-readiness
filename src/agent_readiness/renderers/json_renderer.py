"""JSON renderer. Stable schema (Report.schema). Stdlib only."""

from __future__ import annotations

import json

from agent_readiness.models import Report


def render(report: Report) -> str:
    """Pretty-printed, deterministically-ordered JSON."""
    return json.dumps(report.to_dict(), indent=2, sort_keys=False)
