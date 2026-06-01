"""HTTP JSON API for the bundled scan-and-view server (Bundle D § 7).

Five endpoints:

  ``GET  /api/scans/<scan_id>/snapshot``                  materialized state
  ``GET  /api/scans/<scan_id>/topaction/diff``            preview-only diff
  ``POST /api/scans/<scan_id>/prompts/<prompt_id>/answer`` submit answer
  ``POST /api/scans/<scan_id>/exit``                       Exit-dashboard click
  ``POST /api/scans/<scan_id>/topaction/apply``            Apply-top-action click

All endpoints are localhost-only (same posture as the SPA + ``/data``
routes). No auth, same-origin, no CORS.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import TypeAdapter, ValidationError

from agent_readiness_insights_protocol import (
    PromptAnswer,
    ScanExitedEvent,
)

from agent_readiness.live_scan.events import EventLog
from agent_readiness.live_scan.prompts import PromptLog
from agent_readiness.live_scan.snapshot import build_snapshot


EXIT_FLAG_FILENAME = "exit_requested"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _send_json(handler, status: int, body: dict) -> None:
    payload = json.dumps(body, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _send_text(handler, status: int, body: str) -> None:
    payload = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _read_json_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length") or "0")
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def _scan_exited(scan_dir: Path) -> bool:
    return (scan_dir / EXIT_FLAG_FILENAME).exists()


# ---------------------------------------------------------------------------
# GET /api/scans/<id>/snapshot
# ---------------------------------------------------------------------------


def handle_snapshot_get(handler, scan_dir: Path, workspace_path: Path) -> None:
    """Replay events.jsonl into a WorkspaceScanSnapshot and return it."""
    try:
        snap = build_snapshot(scan_dir, workspace_path)
    except Exception as exc:  # noqa: BLE001
        _send_json(handler, 500, {"error": "snapshot_build_failed", "detail": str(exc)})
        return
    _send_json(handler, 200, json.loads(snap.model_dump_json(exclude_none=True)))


# ---------------------------------------------------------------------------
# POST /api/scans/<id>/prompts/<pid>/answer
# ---------------------------------------------------------------------------


def handle_prompt_answer_post(
    handler,
    scan_dir: Path,
    prompt_id: str,
) -> None:
    if _scan_exited(scan_dir):
        _send_json(handler, 410, {"error": "scan_exited"})
        return

    try:
        body = _read_json_body(handler)
    except json.JSONDecodeError:
        _send_json(handler, 400, {"error": "invalid_json"})
        return

    answer_raw = body.get("answer")
    if answer_raw is None:
        _send_json(handler, 400, {"error": "missing_answer"})
        return

    try:
        adapter = TypeAdapter(PromptAnswer)
        answer = adapter.validate_python(answer_raw)
    except ValidationError as ve:
        _send_json(handler, 422, {"error": "invalid_answer", "detail": ve.errors()})
        return

    # We need a PromptLog scoped to this scan_dir. Construct fresh; the
    # in-memory state is rebuilt from prompts.jsonl on construct.
    event_log = EventLog(scan_dir)
    prompts = PromptLog(scan_dir, event_log)

    if not prompts.is_known(prompt_id):
        _send_json(handler, 404, {"error": "unknown_prompt", "prompt_id": prompt_id})
        return

    already_answered = prompts.is_answered(prompt_id)

    try:
        prompts.answer(prompt_id, answer=answer, source="browser")
    except KeyError:
        _send_json(handler, 404, {"error": "unknown_prompt", "prompt_id": prompt_id})
        return

    status = 200 if not already_answered else 200  # idempotent
    _send_json(handler, status, {
        "accepted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seq": event_log.next_seq - 1,
        "superseded": already_answered,
    })


# ---------------------------------------------------------------------------
# POST /api/scans/<id>/exit
# ---------------------------------------------------------------------------


def handle_exit_post(handler, scan_dir: Path) -> None:
    """Write the exit flag and emit scan.exited.

    Per spec § 5: the scan KEEPS RUNNING; exit only unhooks the skill
    from dashboard mode. The dashboard server stays up until its
    existing idle-timeout.
    """
    try:
        body = _read_json_body(handler)
    except json.JSONDecodeError:
        body = {}

    source = body.get("source", "button")
    if source not in ("button", "chat"):
        _send_json(handler, 400, {"error": "invalid_source"})
        return

    flag = scan_dir / EXIT_FLAG_FILENAME
    if not flag.exists():
        # First exit click — write flag + emit event.
        flag.write_text(json.dumps({
            "source": source,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }))
        event_log = EventLog(scan_dir)
        ev = ScanExitedEvent(
            seq=event_log.next_seq,
            at=datetime.now(timezone.utc),
            source=source,
        )
        event_log.emit(ev)

    _send_json(handler, 200, {
        "exited_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


# ---------------------------------------------------------------------------
# POST /api/scans/<id>/topaction/apply
# ---------------------------------------------------------------------------


_topaction_locks: dict[str, bool] = {}


def handle_topaction_apply_post(
    handler,
    scan_dir: Path,
    scan_id: str,
    workspace_path: Path,
) -> None:
    """Trigger apply_top_action via the engine in-process.

    Rate-limited to 1 in-flight per scan_id (concurrent click → 409).
    """
    if _scan_exited(scan_dir):
        _send_json(handler, 410, {"error": "scan_exited"})
        return

    if _topaction_locks.get(scan_id):
        _send_json(handler, 409, {"error": "apply_in_flight"})
        return

    try:
        body = _read_json_body(handler)
    except json.JSONDecodeError:
        body = {}
    run_verify = bool(body.get("run_verify", True))

    _topaction_locks[scan_id] = True
    try:
        from agent_readiness.live_scan.topaction_adapter import apply_top_action_to_path
        result = apply_top_action_to_path(workspace_path, run_verify=run_verify)
        _send_json(handler, 200, {
            "applied": bool(result.get("applied")),
            "verified": bool(result.get("verified")),
            "output": result.get("output", ""),
        })
    except Exception as exc:  # noqa: BLE001
        _send_json(handler, 500, {"error": "apply_failed", "detail": str(exc)})
    finally:
        _topaction_locks.pop(scan_id, None)


# ---------------------------------------------------------------------------
# GET /api/scans/<id>/topaction/diff
# ---------------------------------------------------------------------------


def handle_topaction_diff_get(handler, scan_dir: Path, workspace_path: Path) -> None:
    """Compute the unified diff the top-action would produce, without applying.

    Read-only; does NOT transition the prompt state. Implementation is
    deferred to a follow-up PR per spec § 15 — endpoint is wired so the
    dashboard can shape its UI, returns 501 until the dry-run path lands.
    """
    if _scan_exited(scan_dir):
        _send_json(handler, 410, {"error": "scan_exited"})
        return
    _send_json(handler, 501, {
        "error": "dry_run_not_implemented",
        "hint": "endpoint reserved; implementation deferred per spec § 15",
    })


# ---------------------------------------------------------------------------
# routing helper used by server.py
# ---------------------------------------------------------------------------


def parse_api_path(path: str) -> Optional[dict]:
    """Recognize an API path and return parts; None if not an API path.

    Strips query/fragment. Returns a dict with ``kind`` and any
    captured segments (``scan_id``, ``prompt_id``).
    """
    if "?" in path:
        path = path.split("?", 1)[0]
    if "#" in path:
        path = path.split("#", 1)[0]
    if path == "/api/scans":
        return {"kind": "scans_list"}
    if path == "/api/workspaces":
        return {"kind": "workspaces_index"}
    if not path.startswith("/api/scans/"):
        return None
    parts = path[len("/api/scans/"):].strip("/").split("/")
    if len(parts) < 1 or not parts[0]:
        return None
    scan_id = parts[0]
    if len(parts) == 1:
        return None
    if parts[1] == "snapshot" and len(parts) == 2:
        return {"kind": "snapshot", "scan_id": scan_id}
    if parts[1] == "exit" and len(parts) == 2:
        return {"kind": "exit", "scan_id": scan_id}
    if parts[1] == "onboarding" and len(parts) == 2:
        return {"kind": "onboarding_get", "scan_id": scan_id}
    if parts[1] == "onboarding" and len(parts) == 3 and parts[2] == "commit":
        return {"kind": "onboarding_commit", "scan_id": scan_id}
    if parts[1] == "reconfigure" and len(parts) == 2:
        return {"kind": "reconfigure", "scan_id": scan_id}
    if parts[1] == "prompts" and len(parts) == 4 and parts[3] == "answer":
        return {"kind": "prompt_answer", "scan_id": scan_id, "prompt_id": parts[2]}
    if parts[1] == "topaction" and len(parts) == 3:
        if parts[2] == "apply":
            return {"kind": "topaction_apply", "scan_id": scan_id}
        if parts[2] == "diff":
            return {"kind": "topaction_diff", "scan_id": scan_id}
    return None


def parse_sse_path(path: str) -> Optional[dict]:
    """Recognize an SSE path: ``/sse/scans/<scan_id>``."""
    if "?" in path:
        base, query = path.split("?", 1)
    else:
        base, query = path, ""
    if not base.startswith("/sse/scans/"):
        return None
    parts = base[len("/sse/scans/"):].strip("/").split("/")
    if len(parts) != 1:
        return None
    out: dict = {"kind": "sse", "scan_id": parts[0]}
    if query:
        for kv in query.split("&"):
            if kv.startswith("since="):
                try:
                    out["since"] = int(kv[len("since="):])
                except ValueError:
                    pass
    return out
