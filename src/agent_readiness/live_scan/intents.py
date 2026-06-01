"""Global scan-intent store: the dashboard queues start/stop intents here
and a user-started agent loop drains them. One JSON file per intent under
``~/.agent-readiness/intents/`` (a directory, not a shared log, so writers
never race and claim/ack is a single atomic write)."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_readiness.live_scan.envelope import atomic_write_json

_VALID_ACTIONS = ("start", "stop")
_TERMINAL = ("done", "failed")
STALE_CLAIM_TTL = timedelta(minutes=5)
DEFAULT_INTENT_RETENTION = 50


def intents_root() -> Path:
    return Path.home() / ".agent-readiness" / "intents"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_for(intent_id: str) -> Path:
    return intents_root() / f"{intent_id}.json"


def _load(intent_id: str) -> dict | None:
    f = _path_for(intent_id)
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def create_intent(action: str, *, path: str | None = None,
                  scan_id: str | None = None) -> dict:
    if action not in _VALID_ACTIONS:
        raise ValueError(
            f"unknown action {action!r}; expected one of {_VALID_ACTIONS}"
        )
    if action == "start" and not path:
        raise ValueError("action 'start' requires a path")
    if action == "stop" and not scan_id:
        raise ValueError("action 'stop' requires a scan_id")
    rec = {
        "id": f"int-{uuid.uuid4().hex[:6]}",
        "action": action,
        "path": path,
        "scan_id": scan_id,
        "status": "pending",
        "created_at": _now(),
        "claimed_at": None,
        "result": None,
    }
    atomic_write_json(_path_for(rec["id"]), rec)
    try:
        prune_intents()
    except OSError:
        pass
    return rec


def list_intents(status: str | None = None) -> list[dict]:
    root = intents_root()
    if not root.is_dir():
        return []
    rows: list[dict] = []
    for f in root.glob("*.json"):
        try:
            rec = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if status is not None and rec.get("status") != status:
            continue
        rows.append(rec)
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows


def claim_intent(intent_id: str) -> dict | None:
    """Atomically move pending → claimed. Returns the record, or None if the
    intent is missing or already claimed-and-fresh. A claim older than
    ``STALE_CLAIM_TTL`` is re-claimable so a crashed agent loop can't wedge
    the queue."""
    rec = _load(intent_id)
    if rec is None:
        return None
    if rec["status"] == "claimed":
        claimed_at = rec.get("claimed_at")
        if claimed_at is not None:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(claimed_at)
            if age < STALE_CLAIM_TTL:
                return None  # someone owns it
    elif rec["status"] != "pending":
        return None  # done/failed are terminal
    rec["status"] = "claimed"
    rec["claimed_at"] = _now()
    atomic_write_json(_path_for(intent_id), rec)
    return rec


def ack_intent(intent_id: str, status: str, result=None) -> dict | None:
    if status not in _TERMINAL:
        raise ValueError(f"ack status must be one of {_TERMINAL}, got {status!r}")
    rec = _load(intent_id)
    if rec is None:
        return None
    rec["status"] = status
    rec["result"] = result
    atomic_write_json(_path_for(intent_id), rec)
    return rec


def prune_intents(keep: int | None = None) -> None:
    """Delete the oldest terminal (done/failed) intents beyond ``keep``.
    ``keep`` defaults to ``AGENT_READINESS_SCAN_RETENTION`` or 50."""
    if keep is None:
        keep = int(os.environ.get("AGENT_READINESS_SCAN_RETENTION",
                                  DEFAULT_INTENT_RETENTION))
    terminal = [r for r in list_intents() if r["status"] in _TERMINAL]
    for rec in terminal[keep:]:
        _path_for(rec["id"]).unlink(missing_ok=True)
