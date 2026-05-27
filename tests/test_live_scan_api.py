"""Tests for the JSON API + path routing (Bundle D).

Covers:

- parse_api_path / parse_sse_path — the central routing helper.
- GET /api/scans/<id>/snapshot — returns WorkspaceScanSnapshot.
- POST /api/scans/<id>/prompts/<pid>/answer — validates body, persists.
- POST /api/scans/<id>/exit — writes flag, emits scan.exited.
- POST /api/scans/<id>/topaction/apply — adapter integration, 500 on
  missing envelope.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

import pytest

from agent_readiness.live_scan.api import (
    EXIT_FLAG_FILENAME,
    parse_api_path,
    parse_sse_path,
)
from agent_readiness.live_scan.events import EventLog, events_path
from agent_readiness.live_scan.prompts import PromptLog
from agent_readiness.live_scan.server import start_server
from agent_readiness_insights_protocol import (
    ClarifyAnswer,
    ClarifyPromptPayload,
)


NOW = datetime(2026, 5, 26, 22, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Path parsing — unit-level, no server needed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,expected", [
    ("/api/scans/abc/snapshot",
     {"kind": "snapshot", "scan_id": "abc"}),
    ("/api/scans/abc/snapshot?cache=0",
     {"kind": "snapshot", "scan_id": "abc"}),
    ("/api/scans/abc/exit",
     {"kind": "exit", "scan_id": "abc"}),
    ("/api/scans/abc/prompts/p-1/answer",
     {"kind": "prompt_answer", "scan_id": "abc", "prompt_id": "p-1"}),
    ("/api/scans/abc/topaction/apply",
     {"kind": "topaction_apply", "scan_id": "abc"}),
    ("/api/scans/abc/topaction/diff",
     {"kind": "topaction_diff", "scan_id": "abc"}),
])
def test_parse_api_path_recognizes(path, expected):
    assert parse_api_path(path) == expected


@pytest.mark.parametrize("path", [
    "/api/scans/abc",
    "/api/scans/",
    "/foo/bar",
    "",
    "/api/scans/abc/unknown",
    "/api/scans/abc/prompts/p-1",
])
def test_parse_api_path_rejects(path):
    assert parse_api_path(path) is None


def test_parse_sse_path_recognizes():
    assert parse_sse_path("/sse/scans/abc") == {"kind": "sse", "scan_id": "abc"}
    assert parse_sse_path("/sse/scans/abc?since=42") == {
        "kind": "sse", "scan_id": "abc", "since": 42,
    }
    assert parse_sse_path("/sse/scans/abc?since=junk") == {
        "kind": "sse", "scan_id": "abc",
    }
    assert parse_sse_path("/api/foo") is None


# ---------------------------------------------------------------------------
# Server fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def server(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    srv = start_server(
        host="127.0.0.1", port=0,
        data_dir=data_dir,
        workspace_path=tmp_path,
    )
    yield srv, data_dir, tmp_path
    srv.shutdown()


def _post_json(srv, path, body):
    url = f"http://{srv.host}:{srv.port}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=5)


def _get_json(srv, path):
    url = f"http://{srv.host}:{srv.port}{path}"
    resp = urllib.request.urlopen(url, timeout=5)
    return json.loads(resp.read().decode("utf-8")), resp


# ---------------------------------------------------------------------------
# GET /api/scans/<id>/snapshot
# ---------------------------------------------------------------------------


def test_snapshot_endpoint_returns_snapshot(server):
    srv, data_dir, _ = server
    body, resp = _get_json(srv, "/api/scans/x/snapshot")
    assert resp.status == 200
    assert body["status"] == "queued"
    assert body["last_seq"] == 0


def test_snapshot_endpoint_reflects_emitted_events(server):
    srv, data_dir, _ = server
    log = EventLog(data_dir)
    from agent_readiness_insights_protocol import ScanCompletedEvent
    log.emit(ScanCompletedEvent(seq=0, at=NOW, overall_score=82.5,
                                 pillar_scores={"feedback": 70.0}))
    body, _ = _get_json(srv, "/api/scans/x/snapshot")
    assert body["status"] == "completed"
    assert body["overall_score"] == 82.5
    assert body["pillar_scores"]["feedback"] == 70.0


# ---------------------------------------------------------------------------
# POST /api/scans/<id>/prompts/<pid>/answer
# ---------------------------------------------------------------------------


def test_prompt_answer_accepts_valid_payload(server):
    srv, data_dir, _ = server
    el = EventLog(data_dir)
    pl = PromptLog(data_dir, el)
    pid = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="d"),
    )
    resp = _post_json(srv, f"/api/scans/x/prompts/{pid}/answer", {
        "answer": {"type": "clarify", "freeform": "user said this"},
    })
    body = json.loads(resp.read().decode())
    assert resp.status == 200
    assert body["superseded"] is False

    # Re-construct PromptLog from disk to verify persistence.
    pl2 = PromptLog(data_dir, EventLog(data_dir))
    assert pl2.status(pid) == "answered"


def test_prompt_answer_404_on_unknown_pid(server):
    srv, _, _ = server
    try:
        _post_json(srv, "/api/scans/x/prompts/p-nope/answer", {
            "answer": {"type": "clarify", "freeform": "x"},
        })
        raised = False
    except urllib.error.HTTPError as e:
        raised = (e.code == 404)
    assert raised


def test_prompt_answer_422_on_invalid_body(server):
    import urllib.error
    srv, data_dir, _ = server
    el = EventLog(data_dir)
    pl = PromptLog(data_dir, el)
    pid = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="d"),
    )
    try:
        _post_json(srv, f"/api/scans/x/prompts/{pid}/answer", {
            "answer": {"type": "bogus", "freeform": "x"},
        })
        raised = False
    except urllib.error.HTTPError as e:
        raised = (e.code == 422)
    assert raised


def test_prompt_answer_410_after_exit(server):
    import urllib.error
    srv, data_dir, _ = server
    el = EventLog(data_dir)
    pl = PromptLog(data_dir, el)
    pid = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="d"),
    )
    # Trip the exit flag.
    _post_json(srv, "/api/scans/x/exit", {"source": "button"})
    try:
        _post_json(srv, f"/api/scans/x/prompts/{pid}/answer", {
            "answer": {"type": "clarify", "freeform": "x"},
        })
        raised = False
    except urllib.error.HTTPError as e:
        raised = (e.code == 410)
    assert raised


# ---------------------------------------------------------------------------
# POST /api/scans/<id>/exit
# ---------------------------------------------------------------------------


def test_exit_writes_flag_and_emits_event(server):
    srv, data_dir, _ = server
    resp = _post_json(srv, "/api/scans/x/exit", {"source": "button"})
    assert resp.status == 200
    assert (data_dir / EXIT_FLAG_FILENAME).exists()
    # And the SSE event log carries scan.exited.
    events = [json.loads(line)
              for line in events_path(data_dir).read_text().splitlines()
              if line.strip()]
    assert any(e["event"] == "scan.exited" for e in events)


def test_exit_is_idempotent(server):
    srv, data_dir, _ = server
    _post_json(srv, "/api/scans/x/exit", {"source": "button"})
    _post_json(srv, "/api/scans/x/exit", {"source": "button"})
    _post_json(srv, "/api/scans/x/exit", {"source": "button"})
    events = [json.loads(line)
              for line in events_path(data_dir).read_text().splitlines()
              if line.strip()]
    assert sum(1 for e in events if e["event"] == "scan.exited") == 1


def test_exit_rejects_invalid_source(server):
    import urllib.error
    srv, _, _ = server
    try:
        _post_json(srv, "/api/scans/x/exit", {"source": "rocket"})
        raised = False
    except urllib.error.HTTPError as e:
        raised = (e.code == 400)
    assert raised


# ---------------------------------------------------------------------------
# POST /api/scans/<id>/topaction/apply
# ---------------------------------------------------------------------------


def test_topaction_apply_no_envelope_returns_200_with_skipped(server):
    """No live/latest envelope yet → adapter returns applied=False with a
    diagnostic message. We expose this as 200 because the dashboard wants
    to show the friendly 'nothing to apply' state, not a server error."""
    srv, _, _ = server
    resp = _post_json(srv, "/api/scans/x/topaction/apply", {"run_verify": False})
    body = json.loads(resp.read().decode())
    assert resp.status == 200
    assert body["applied"] is False
    assert "no scan envelope" in body["output"].lower()


def test_topaction_diff_returns_501(server):
    import urllib.error
    srv, _, _ = server
    try:
        _get_json(srv, "/api/scans/x/topaction/diff")
        raised = False
    except urllib.error.HTTPError as e:
        raised = (e.code == 501)
    assert raised


# ---------------------------------------------------------------------------
# 404/405 fall-through
# ---------------------------------------------------------------------------


def test_get_on_post_only_endpoint_returns_405(server):
    import urllib.error
    srv, _, _ = server
    try:
        _get_json(srv, "/api/scans/x/exit")
        raised = False
    except urllib.error.HTTPError as e:
        raised = (e.code == 405)
    assert raised


def test_post_to_unknown_path_returns_404(server):
    import urllib.error
    srv, _, _ = server
    try:
        _post_json(srv, "/api/scans/x/totally/fake", {})
        raised = False
    except urllib.error.HTTPError as e:
        raised = (e.code == 404)
    assert raised
