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


from agent_readiness.live_scan.worker import emit_onboarding_committed


_VALID_TYPES = {"single_repo", "monorepo", "workspace"}


def _next_seq(scan_dir: Path) -> int:
    """Highest seq in events.jsonl + 1. Zero if file missing/empty."""
    events_file = scan_dir / "events.jsonl"
    if not events_file.is_file():
        return 0
    max_seq = -1
    for line in events_file.read_text().splitlines():
        try:
            doc = json.loads(line)
            if isinstance(doc.get("seq"), int) and doc["seq"] > max_seq:
                max_seq = doc["seq"]
        except json.JSONDecodeError:
            continue
    return max_seq + 1


def commit_onboarding(scan_dir: Path, request_body: dict) -> tuple[dict, int]:
    """``POST /api/scans/<id>/onboarding/commit`` — user hit Start.

    Body: ``{"type": WorkspaceType, "selected_paths": [str]}``.
    Persists the selection (bumping revision), emits ``onboarding.committed``,
    kicks off the worker pool."""
    type_ = request_body.get("type")
    selected_paths = request_body.get("selected_paths")
    if type_ not in _VALID_TYPES:
        return {"error": f"`type` must be one of {sorted(_VALID_TYPES)}, got {type_!r}"}, 400
    if not isinstance(selected_paths, list) or not all(isinstance(p, str) for p in selected_paths):
        return {"error": "`selected_paths` must be a list of strings"}, 400

    now = datetime.now(timezone.utc)
    state = commit_selection(
        scan_dir,
        type=type_,
        selected_paths=selected_paths,
        committed_at=now,
    )
    revision = state.selection.revision

    emit_onboarding_committed(
        scan_dir,
        type=type_,
        selected_paths=selected_paths,
        revision=revision,
        start_seq=_next_seq(scan_dir),
    )

    _start_worker_pool(
        scan_dir,
        type=type_,
        selected_paths=selected_paths,
        revision=revision,
    )

    return {
        "status": "scanning",
        "revision": revision,
        "next_url": f"/#/live/{state.scan_id}",
    }, 200


def _start_worker_pool(
    scan_dir: Path,
    *,
    type: str,
    selected_paths: list[str],
    revision: int,
) -> None:
    """Start the scan worker pool for `selected_paths`."""
    from agent_readiness.live_scan.worker import start_worker_pool

    start_worker_pool(scan_dir, paths=selected_paths)
