"""End-to-end tests for the SSE handler + HTTP server integration (Bundle D).

The SSE handler streams events.jsonl over text/event-stream. These tests
spin up the real bundled server, write events to the on-disk log from a
test thread, and assert the browser-side wire bytes are correct.
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from agent_readiness.live_scan.events import EventLog
from agent_readiness.live_scan.server import start_server
from agent_readiness_insights_protocol import (
    RepoQueuedEvent,
    ScanCompletedEvent,
    ScanExitedEvent,
    ScanStartedEvent,
)


NOW = datetime(2026, 5, 26, 22, 30, 0, tzinfo=timezone.utc)


def _start(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    srv = start_server(
        host="127.0.0.1", port=0,
        data_dir=data_dir,
        workspace_path=tmp_path,
    )
    return srv, data_dir


def _readlines_until_blank(resp, max_bytes: int = 64 * 1024) -> str:
    """Read SSE bytes until we hit a blank line OR timeout."""
    buf = b""
    while len(buf) < max_bytes:
        chunk = resp.read(256)
        if not chunk:
            break
        buf += chunk
        if b"\n\n" in buf:
            break
    return buf.decode("utf-8", errors="replace")


def test_sse_returns_204_when_no_events_to_send(tmp_path):
    srv, data_dir = _start(tmp_path)
    try:
        url = f"http://{srv.host}:{srv.port}/sse/scans/abc?since=99"
        # urllib treats 2xx as success — 204 just gives an empty body.
        resp = urllib.request.urlopen(url, timeout=3)
        assert resp.status == 204
        assert resp.read() == b""
    finally:
        srv.shutdown()


def test_sse_replays_existing_events_in_order(tmp_path):
    srv, data_dir = _start(tmp_path)
    try:
        log = EventLog(data_dir)
        log.emit(ScanStartedEvent(seq=0, at=NOW, started_at=NOW))
        log.emit(RepoQueuedEvent(seq=0, at=NOW, repo_id="r1"))
        log.emit(ScanExitedEvent(seq=0, at=NOW, source="button"))

        url = f"http://{srv.host}:{srv.port}/sse/scans/abc"
        resp = urllib.request.urlopen(url, timeout=5)
        try:
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "text/event-stream"
            body = resp.read().decode("utf-8")
        finally:
            resp.close()

        # Three events on the wire — exit terminates the stream.
        assert "event: scan.started" in body
        assert "event: repo.queued" in body
        assert "event: scan.exited" in body
        # SSE id line uses the seq.
        assert "id: 0" in body
        assert "id: 1" in body
        assert "id: 2" in body
        # Each event ends in a blank line.
        assert body.count("\n\n") >= 3
    finally:
        srv.shutdown()


def test_sse_honors_last_event_id_header(tmp_path):
    srv, data_dir = _start(tmp_path)
    try:
        log = EventLog(data_dir)
        log.emit(ScanStartedEvent(seq=0, at=NOW, started_at=NOW))
        log.emit(ScanCompletedEvent(seq=0, at=NOW, overall_score=90.0, pillar_scores={}))
        log.emit(ScanExitedEvent(seq=0, at=NOW, source="button"))

        url = f"http://{srv.host}:{srv.port}/sse/scans/abc"
        req = urllib.request.Request(url, headers={"Last-Event-ID": "0"})
        resp = urllib.request.urlopen(req, timeout=5)
        try:
            body = resp.read().decode("utf-8")
        finally:
            resp.close()

        # seq 0 was scan.started; client says they have it — should be skipped.
        assert "event: scan.started" not in body
        assert "event: scan.completed" in body
        assert "event: scan.exited" in body
    finally:
        srv.shutdown()


def test_sse_streams_live_events_then_exits(tmp_path):
    srv, data_dir = _start(tmp_path)
    try:
        log = EventLog(data_dir)
        log.emit(ScanStartedEvent(seq=0, at=NOW, started_at=NOW))

        # Append more events from a background thread AFTER the request
        # has started, so the tail loop has to pick them up live.
        def _producer():
            time.sleep(0.4)
            log.emit(RepoQueuedEvent(seq=0, at=NOW, repo_id="r1"))
            log.emit(RepoQueuedEvent(seq=0, at=NOW, repo_id="r2"))
            time.sleep(0.2)
            log.emit(ScanExitedEvent(seq=0, at=NOW, source="chat"))

        t = threading.Thread(target=_producer, daemon=True)
        t.start()

        url = f"http://{srv.host}:{srv.port}/sse/scans/abc"
        resp = urllib.request.urlopen(url, timeout=10)
        try:
            body = resp.read().decode("utf-8")
        finally:
            resp.close()
        t.join(timeout=5)

        # All four events made it.
        assert "event: scan.started" in body
        assert "event: repo.queued" in body
        assert "event: scan.exited" in body
        # Order preserved.
        i_started = body.index("event: scan.started")
        i_exit = body.index("event: scan.exited")
        assert i_started < i_exit
    finally:
        srv.shutdown()
