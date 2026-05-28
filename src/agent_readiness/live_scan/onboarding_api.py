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


from agent_readiness.live_scan.worker import reconfigure_scan


def reconfigure_onboarding(scan_dir: Path) -> tuple[dict, int]:
    """``POST /api/scans/<id>/reconfigure`` — user clicked Reconfigure.

    Kills the running worker pool, deletes live.json + results/*, emits
    ``onboarding.reconfigured``. Wizard resumes from the persisted
    selection at the Pick step (frontend handles routing)."""
    state = load(scan_dir)
    if state is None:
        return {"error": "no onboarding.json for this scan"}, 404
    if state.selection is None:
        return {"error": "no prior selection — cannot reconfigure a scan that never started"}, 400

    previous_revision = state.selection.revision

    _kill_worker_pool(scan_dir)
    reconfigure_scan(
        scan_dir,
        previous_revision=previous_revision,
        start_seq=_next_seq(scan_dir),
    )

    return {
        "status": "reconfigured",
        "previous_revision": previous_revision,
        "next_url": f"/#/onboarding/{state.scan_id}",
    }, 200


def _kill_worker_pool(scan_dir: Path) -> None:
    """Send SIGTERM to the worker subprocess associated with this scan."""
    from agent_readiness.live_scan.pidfile import PidStatus, verify_pidfile

    pidfile = scan_dir / "daemon.pid"
    if verify_pidfile(pidfile) != PidStatus.LIVE:
        return
    try:
        data = json.loads(pidfile.read_text())
        os.kill(data["pid"], signal.SIGTERM)
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass


def list_scans() -> tuple[dict, int]:
    """``GET /api/scans`` — list every scan under ~/.agent-readiness/scans/.

    Newest first by ``created_at``. Each row carries scan_id, type,
    repo count, status, and timestamps. Used by the dashboard's
    /workspaces history page."""
    scans_root = Path.home() / ".agent-readiness" / "scans"
    if not scans_root.is_dir():
        return {"scans": []}, 200

    rows: list[dict] = []
    for scan_dir in scans_root.iterdir():
        if not scan_dir.is_dir():
            continue
        state = load(scan_dir)
        if state is None:
            continue
        status = "onboarding" if state.selection is None else "running"
        if (scan_dir / "live.json").exists():
            try:
                live = json.loads((scan_dir / "live.json").read_text())
                if live.get("status") == "completed":
                    status = "completed"
                elif live.get("status") == "failed":
                    status = "failed"
            except (json.JSONDecodeError, OSError):
                pass
        rows.append({
            "scan_id": state.scan_id,
            "type": state.committed_type,
            "created_at": state.created_at.isoformat(),
            "status": status,
            "repos_total": len(state.enumeration.repos),
            "repos_selected": (
                len(state.selection.selected_paths) if state.selection else 0
            ),
        })

    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return {"scans": rows}, 200
