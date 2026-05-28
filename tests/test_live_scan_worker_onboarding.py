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
