"""The worker must emit onboarding.enumerated + onboarding.classified
into events.jsonl BEFORE any repo.* events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def test_worker_emits_two_onboarding_events_first(tmp_path: Path):
    from agent_readiness.enumerate_git import inspect as do_inspect
    from agent_readiness.live_scan.worker import emit_onboarding_events
    from agent_readiness.onboarding import (
        OnboardingState,
        save,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "alpha").mkdir()
    (workspace / "alpha" / ".git").mkdir()
    (workspace / "beta").mkdir()
    (workspace / "beta" / ".git").mkdir()

    scan_dir = tmp_path / "scan-1"
    scan_dir.mkdir()

    inspect = do_inspect(workspace)
    state = OnboardingState(
        scan_id="scan-1",
        committed_type="workspace",
        enumeration=inspect.enumeration,
        classification=inspect.classification,
        selection=None,
        created_at=datetime.now(timezone.utc),
    )
    save(scan_dir, state)

    seq_after = emit_onboarding_events(scan_dir, state, start_seq=0)
    assert seq_after == 2

    events_file = scan_dir / "events.jsonl"
    lines = events_file.read_text().splitlines()
    assert len(lines) == 2
    e0 = json.loads(lines[0])
    e1 = json.loads(lines[1])
    assert e0["event"] == "onboarding.enumerated"
    assert e0["seq"] == 0
    assert e0["git_repos_found"] == 2
    assert e1["event"] == "onboarding.classified"
    assert e1["seq"] == 1
    assert e1["suggested_type"] == "workspace"


def test_worker_emits_onboarding_committed_event(tmp_path: Path):
    """Called when the user clicks Start. Appends one event with the
    user's chosen type and selected_paths."""
    from agent_readiness.live_scan.worker import emit_onboarding_committed

    scan_dir = tmp_path / "scan-2"
    scan_dir.mkdir()
    # Seed events.jsonl with two prior events so start_seq=2.
    (scan_dir / "events.jsonl").write_text(
        '{"event":"a","seq":0}\n{"event":"b","seq":1}\n'
    )
    next_seq = emit_onboarding_committed(
        scan_dir,
        type="workspace",
        selected_paths=["a", "b"],
        revision=1,
        start_seq=2,
    )
    assert next_seq == 3
    lines = (scan_dir / "events.jsonl").read_text().splitlines()
    e = json.loads(lines[2])
    assert e["event"] == "onboarding.committed"
    assert e["seq"] == 2
    assert e["type"] == "workspace"
    assert e["selected_paths"] == ["a", "b"]
    assert e["revision"] == 1


def test_worker_reconfigure_emits_event_and_clears_results(tmp_path: Path):
    from agent_readiness.live_scan.worker import reconfigure_scan

    scan_dir = tmp_path / "scan-3"
    scan_dir.mkdir()
    (scan_dir / "events.jsonl").write_text("")
    (scan_dir / "live.json").write_text('{"x":1}')
    (scan_dir / "results").mkdir()
    (scan_dir / "results" / "repo-a").mkdir()
    (scan_dir / "results" / "repo-a" / "score.json").write_text("{}")
    (scan_dir / "onboarding.json").write_text('{"keep": "me"}')

    next_seq = reconfigure_scan(scan_dir, previous_revision=1, start_seq=0)
    assert next_seq == 1

    # live.json and results/ are gone; events.jsonl and onboarding.json remain.
    assert not (scan_dir / "live.json").exists()
    assert not (scan_dir / "results").exists()
    assert (scan_dir / "events.jsonl").exists()
    assert (scan_dir / "onboarding.json").exists()

    line = (scan_dir / "events.jsonl").read_text().strip()
    e = json.loads(line)
    assert e["event"] == "onboarding.reconfigured"
    assert e["previous_revision"] == 1
