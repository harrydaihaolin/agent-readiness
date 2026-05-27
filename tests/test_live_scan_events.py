"""Tests for live_scan.events (Bundle D, agent-readiness v3.4.0).

The append-only events.jsonl log is the on-disk SSE bus. Covers:

- Monotonic seq assignment + crash-recovery via _compute_next_seq.
- Throttling via maybe_emit.
- Validated emit via SSEEvent discriminated union.
- read_after_seq for snapshot replay.
- tail() with stop_predicate (lightweight test; full SSE integration
  test lives in test_live_scan_sse.py).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

from agent_readiness.live_scan.events import EventLog, events_path
from agent_readiness_insights_protocol import (
    RepoQueuedEvent,
    ScanStartedEvent,
)


def test_append_assigns_monotonic_seq(tmp_path):
    log = EventLog(tmp_path)
    assert log.next_seq == 0
    a = log.append({"event": "scan.started", "at": "2026-01-01T00:00:00Z"})
    b = log.append({"event": "repo.queued", "repo_id": "r1", "at": "2026-01-01T00:00:01Z"})
    c = log.append({"event": "scan.completed", "overall_score": 100.0,
                    "pillar_scores": {}, "at": "2026-01-01T00:00:02Z"})
    assert (a, b, c) == (0, 1, 2)
    assert log.next_seq == 3


def test_append_overrides_stale_seq(tmp_path):
    log = EventLog(tmp_path)
    log.append({"event": "x", "seq": 99})
    log.append({"event": "y", "seq": 99})  # caller passed stale seq
    lines = events_path(tmp_path).read_text().strip().splitlines()
    assert [json.loads(line)["seq"] for line in lines] == [0, 1]


def test_emit_validates_via_sse_event_union(tmp_path):
    log = EventLog(tmp_path)
    ev = ScanStartedEvent(seq=0, at=datetime.now(timezone.utc),
                          started_at=datetime.now(timezone.utc))
    log.emit(ev)
    on_disk = json.loads(events_path(tmp_path).read_text().strip())
    assert on_disk["event"] == "scan.started"
    assert on_disk["seq"] == 0


def test_emit_rejects_invalid_event_dict(tmp_path):
    log = EventLog(tmp_path)
    with pytest.raises(Exception):  # ValidationError from pydantic
        log.emit({"event": "totally.fake.event", "seq": 0,
                  "at": datetime.now(timezone.utc)})


def test_recovers_next_seq_from_existing_file(tmp_path):
    log = EventLog(tmp_path)
    for i in range(5):
        log.append({"event": "x", "seq": i})
    log2 = EventLog(tmp_path)
    assert log2.next_seq == 5
    log2.append({"event": "y"})
    assert log2.next_seq == 6
    seqs = [json.loads(line)["seq"]
            for line in events_path(tmp_path).read_text().strip().splitlines()]
    assert seqs == [0, 1, 2, 3, 4, 5]


def test_recovers_from_torn_tail(tmp_path):
    """Crash mid-append left a partial line — recovery should ignore it."""
    log = EventLog(tmp_path)
    log.append({"event": "x"})
    log.append({"event": "y"})
    with events_path(tmp_path).open("a", encoding="utf-8") as f:
        f.write('{"event": "tor')  # no newline, no closing brace
    log2 = EventLog(tmp_path)
    assert log2.next_seq == 2  # ignored the torn line


def test_read_after_seq_filters_correctly(tmp_path):
    log = EventLog(tmp_path)
    for i in range(5):
        log.append({"event": "x", "i": i})
    seen = list(log.read_after_seq(after_seq=2))
    assert [e["seq"] for e in seen] == [3, 4]


def test_read_all_yields_in_order(tmp_path):
    log = EventLog(tmp_path)
    for i in range(3):
        log.append({"event": "x", "i": i})
    assert [e["seq"] for e in log.read_all()] == [0, 1, 2]


def test_maybe_emit_throttles_close_calls(tmp_path):
    log = EventLog(tmp_path)
    ev1 = RepoQueuedEvent(seq=0, at=datetime.now(timezone.utc), repo_id="r1")
    ev2 = RepoQueuedEvent(seq=0, at=datetime.now(timezone.utc), repo_id="r1")
    ev3 = RepoQueuedEvent(seq=0, at=datetime.now(timezone.utc), repo_id="r2")

    a = log.maybe_emit(ev1, throttle_key=("repo.queued", "r1"), min_interval_s=10.0)
    b = log.maybe_emit(ev2, throttle_key=("repo.queued", "r1"), min_interval_s=10.0)
    c = log.maybe_emit(ev3, throttle_key=("repo.queued", "r2"), min_interval_s=10.0)
    assert a == 0
    assert b is None  # dropped — same key, within window
    assert c == 1     # different key, allowed


def test_maybe_emit_allows_after_window(tmp_path):
    log = EventLog(tmp_path)
    ev = RepoQueuedEvent(seq=0, at=datetime.now(timezone.utc), repo_id="r1")
    a = log.maybe_emit(ev, throttle_key=("repo.queued", "r1"), min_interval_s=0.01)
    time.sleep(0.02)
    b = log.maybe_emit(ev, throttle_key=("repo.queued", "r1"), min_interval_s=0.01)
    assert a == 0
    assert b == 1


def test_tail_stops_on_predicate(tmp_path):
    log = EventLog(tmp_path)
    log.append({"event": "scan.queued"})
    log.append({"event": "scan.exited"})
    seen = []
    for ev in log.tail(
        after_seq=-1,
        poll_interval_s=0.01,
        stop_predicate=lambda e: e is not None and e.get("event") == "scan.exited",
    ):
        seen.append(ev["event"])
    assert seen == ["scan.queued", "scan.exited"]
