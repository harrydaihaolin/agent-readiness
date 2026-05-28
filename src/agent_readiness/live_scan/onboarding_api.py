"""HTTP endpoints for the dashboard wizard.

Three POST endpoints (commit, reconfigure) and one GET (onboarding state)
plus one cross-scan GET (history index). Mounted by
``live_scan/server.py`` under the existing scan-and-view HTTP server.

All handlers return ``(body_dict, http_status_int)``. The server adapter
serializes ``body_dict`` to JSON. Errors are ``{"error": "..."}``.
"""

from __future__ import annotations

import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

from agent_readiness.onboarding import (
    commit_selection,
    load,
    path_for,
)


def path_for_scan(scan_id: str) -> Path:
    """Resolve <home>/.agent-readiness/scans/<scan_id> for the HTTP layer."""
    return path_for(scan_id)


def get_onboarding(scan_dir: Path) -> tuple[dict, int]:
    """``GET /api/scans/<id>/onboarding`` — return the persisted state."""
    state = load(scan_dir)
    if state is None:
        return {"error": "no onboarding.json for this scan"}, 404
    return json.loads(state.model_dump_json()), 200
