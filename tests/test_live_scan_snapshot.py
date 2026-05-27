"""Tests for live_scan.snapshot (Bundle D).

build_snapshot folds events.jsonl into a WorkspaceScanSnapshot. The
output IS the contract for ``GET /api/scans/<id>/snapshot``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agent_readiness.live_scan.events import EventLog
from agent_readiness.live_scan.prompts import PromptLog
from agent_readiness.live_scan.snapshot import build_snapshot
from agent_readiness_insights_protocol import (
    ClarifyAnswer,
    ClarifyPromptPayload,
    RepoFindingCounts,
    RepoQueuedEvent,
    RepoScanCompletedEvent,
    RepoScanStartedEvent,
    ScanChild,
    ScanCompletedEvent,
    ScanExitedEvent,
    ScanQueuedEvent,
    ScanStartedEvent,
)


NOW = datetime(2026, 5, 26, 22, 30, 0, tzinfo=timezone.utc)


def test_snapshot_empty_log_is_queued(tmp_path):
    snap = build_snapshot(tmp_path, workspace_path=tmp_path)
    assert snap.status == "queued"
    assert snap.last_seq == 0
    assert snap.children == []


def test_snapshot_after_scan_started(tmp_path):
    log = EventLog(tmp_path)
    log.emit(ScanQueuedEvent(
        seq=0, at=NOW,
        workspace_path=str(tmp_path),
        children=[ScanChild(id="r1", name="rules", path="/x/r1"),
                  ScanChild(id="r2", name="mcp", path="/x/r2")],
        total=2,
    ))
    log.emit(ScanStartedEvent(seq=0, at=NOW, started_at=NOW))
    snap = build_snapshot(tmp_path, workspace_path=tmp_path)
    assert snap.status == "running"
    assert len(snap.children) == 2
    assert snap.repo_states == {"r1": "queued", "r2": "queued"}


def test_snapshot_aggregates_per_repo_state(tmp_path):
    log = EventLog(tmp_path)
    log.emit(ScanQueuedEvent(seq=0, at=NOW, workspace_path=str(tmp_path),
                              children=[ScanChild(id="r1", name="r1", path="/r1")],
                              total=1))
    log.emit(ScanStartedEvent(seq=0, at=NOW, started_at=NOW))
    log.emit(RepoQueuedEvent(seq=0, at=NOW, repo_id="r1"))
    log.emit(RepoScanStartedEvent(seq=0, at=NOW, repo_id="r1", started_at=NOW))
    log.emit(RepoScanCompletedEvent(
        seq=0, at=NOW, repo_id="r1",
        score=87.5,
        pillar_scores={"feedback": 80.0},
        finding_counts=RepoFindingCounts(warn=3, error=0, not_measured=1),
        completed_at=NOW,
    ))
    snap = build_snapshot(tmp_path, workspace_path=tmp_path)
    assert snap.repo_states["r1"] == "completed"
    assert snap.repo_scores["r1"] == 87.5
    assert snap.repo_finding_counts["r1"].warn == 3
    assert snap.repo_finding_counts["r1"].not_measured == 1


def test_snapshot_terminal_completed_carries_overall(tmp_path):
    log = EventLog(tmp_path)
    log.emit(ScanCompletedEvent(
        seq=0, at=NOW,
        overall_score=82.5,
        pillar_scores={"feedback": 70.0, "safety": 95.0},
    ))
    snap = build_snapshot(tmp_path, workspace_path=tmp_path)
    assert snap.status == "completed"
    assert snap.overall_score == 82.5
    assert snap.pillar_scores == {"feedback": 70.0, "safety": 95.0}


def test_snapshot_exited_carries_source(tmp_path):
    log = EventLog(tmp_path)
    log.emit(ScanExitedEvent(seq=0, at=NOW, source="button"))
    snap = build_snapshot(tmp_path, workspace_path=tmp_path)
    assert snap.status == "exited"
    assert snap.mode_exit_requested is True
    assert snap.exit_source == "button"


def test_snapshot_pending_and_used_default_prompts(tmp_path):
    el = EventLog(tmp_path)
    pl = PromptLog(tmp_path, el)
    p1 = pl.enqueue(
        payload=ClarifyPromptPayload(question="open?"),
        default_action=ClarifyAnswer(freeform="d"),
    )
    p2 = pl.enqueue(
        payload=ClarifyPromptPayload(question="expired?"),
        default_action=ClarifyAnswer(freeform="d"),
    )
    pl.expire(p2)

    snap = build_snapshot(tmp_path, workspace_path=tmp_path)
    pending_ids = {p.prompt_id for p in snap.pending_prompts}
    assert pending_ids == {p1}
    assert p2 in snap.default_used_for


def test_snapshot_last_seq_advances_with_events(tmp_path):
    log = EventLog(tmp_path)
    for _ in range(7):
        log.emit(RepoQueuedEvent(seq=0, at=NOW, repo_id="r1"))
    snap = build_snapshot(tmp_path, workspace_path=tmp_path)
    assert snap.last_seq == 6  # 0..6 inclusive


def test_snapshot_roundtrips_through_protocol_model(tmp_path):
    """Snapshot is what the wire serializes — assert JSON round-trip works
    via the Pydantic model so a browser parser sees the same thing."""
    log = EventLog(tmp_path)
    log.emit(ScanCompletedEvent(seq=0, at=NOW, overall_score=90.0, pillar_scores={}))
    snap = build_snapshot(tmp_path, workspace_path=tmp_path)
    blob = snap.model_dump_json()
    from agent_readiness_insights_protocol import WorkspaceScanSnapshot
    rehydrated = WorkspaceScanSnapshot.model_validate_json(blob)
    assert rehydrated == snap
