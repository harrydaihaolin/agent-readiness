"""Tests for the onboarding HTTP endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


NOW = datetime(2026, 5, 27, 15, 0, 0, tzinfo=timezone.utc)


def _seed_onboarding(scan_dir: Path, scan_id: str = "scan-x") -> None:
    from agent_readiness.onboarding import (
        EnumerationResult,
        OnboardingClassification,
        OnboardingState,
        save,
    )

    save(scan_dir, OnboardingState(
        scan_id=scan_id,
        committed_type="workspace",
        enumeration=EnumerationResult(
            root="/x", root_has_git=False, repos=[],
            directories_walked=1, elapsed_ms=1,
        ),
        classification=OnboardingClassification(
            suggested_type="workspace", confidence="medium", rationale="x",
        ),
        selection=None,
        created_at=NOW,
    ))


def test_get_onboarding_returns_state(tmp_path: Path):
    from agent_readiness.live_scan.onboarding_api import get_onboarding

    _seed_onboarding(tmp_path)
    body, status = get_onboarding(tmp_path)
    assert status == 200
    assert body["scan_id"] == "scan-x"
    assert body["committed_type"] == "workspace"
    assert body["selection"] is None


def test_get_onboarding_returns_404_when_missing(tmp_path: Path):
    from agent_readiness.live_scan.onboarding_api import get_onboarding

    body, status = get_onboarding(tmp_path)
    assert status == 404
    assert "error" in body


def test_commit_onboarding_updates_state_and_emits_event(tmp_path: Path, monkeypatch):
    from agent_readiness.live_scan.onboarding_api import commit_onboarding
    from agent_readiness.onboarding import load

    _seed_onboarding(tmp_path)

    # Stub the worker-pool launcher so the test doesn't try to start subprocesses.
    started = {}
    def fake_start(scan_dir, *, type, selected_paths, revision):
        started["scan_dir"] = scan_dir
        started["type"] = type
        started["selected_paths"] = selected_paths
        started["revision"] = revision
    monkeypatch.setattr(
        "agent_readiness.live_scan.onboarding_api._start_worker_pool",
        fake_start,
    )

    body, status = commit_onboarding(
        tmp_path,
        request_body={
            "type": "workspace",
            "selected_paths": ["a", "b"],
        },
    )
    assert status == 200
    assert body["status"] == "scanning"
    assert body["revision"] == 1

    # Selection persisted.
    state = load(tmp_path)
    assert state.selection.revision == 1
    assert state.selection.selected_paths == ["a", "b"]

    # Event emitted.
    events = (tmp_path / "events.jsonl").read_text().splitlines()
    assert any('"onboarding.committed"' in line for line in events)

    # Worker pool launched.
    assert started["type"] == "workspace"
    assert started["selected_paths"] == ["a", "b"]
    assert started["revision"] == 1


def test_commit_onboarding_validates_type_in_request_body(tmp_path: Path):
    from agent_readiness.live_scan.onboarding_api import commit_onboarding

    _seed_onboarding(tmp_path)
    body, status = commit_onboarding(tmp_path, request_body={
        "type": "garbage",
        "selected_paths": [],
    })
    assert status == 400
    assert "error" in body


def test_reconfigure_kills_workers_and_clears_results(tmp_path: Path, monkeypatch):
    from agent_readiness.live_scan.onboarding_api import reconfigure_onboarding
    from agent_readiness.onboarding import (
        OnboardingSelection,
        load,
        save,
    )

    _seed_onboarding(tmp_path)

    # Add a selection (so revision = 1) and some results.
    state = load(tmp_path)
    state = state.model_copy(update={
        "selection": OnboardingSelection(
            type="workspace",
            selected_paths=["a"],
            revision=1,
            committed_at=NOW,
        ),
    })
    save(tmp_path, state)
    (tmp_path / "live.json").write_text("{}")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "x").mkdir()

    killed = []
    monkeypatch.setattr(
        "agent_readiness.live_scan.onboarding_api._kill_worker_pool",
        lambda d: killed.append(d),
    )

    body, status = reconfigure_onboarding(tmp_path)
    assert status == 200
    assert body["status"] == "reconfigured"
    assert body["next_url"].endswith("/#/onboarding/scan-x")
    assert killed == [tmp_path]
    assert not (tmp_path / "live.json").exists()
    assert not (tmp_path / "results").exists()
    # onboarding.json preserved.
    assert (tmp_path / "onboarding.json").exists()


def test_reconfigure_404_when_no_prior_selection(tmp_path: Path):
    """Can only reconfigure a committed scan."""
    from agent_readiness.live_scan.onboarding_api import reconfigure_onboarding

    _seed_onboarding(tmp_path)
    body, status = reconfigure_onboarding(tmp_path)
    assert status == 400
    assert "no prior selection" in body["error"]


def test_list_scans_returns_committed_scans_newest_first(tmp_path: Path, monkeypatch):
    from agent_readiness.live_scan.onboarding_api import list_scans

    monkeypatch.setenv("HOME", str(tmp_path))
    home_scans = tmp_path / ".agent-readiness" / "scans"
    home_scans.mkdir(parents=True)

    # Two scans: scan-old, scan-new.
    for sid, ts in [("scan-old", datetime(2026, 1, 1, tzinfo=timezone.utc)),
                    ("scan-new", datetime(2026, 5, 27, tzinfo=timezone.utc))]:
        d = home_scans / sid
        d.mkdir()
        _seed_onboarding(d, scan_id=sid)
        # Patch created_at on the disk file.
        s = (d / "onboarding.json").read_text()
        s = s.replace(NOW.isoformat(), ts.isoformat())
        (d / "onboarding.json").write_text(s)

    body, status = list_scans()
    assert status == 200
    assert len(body["scans"]) == 2
    # Newest first.
    assert body["scans"][0]["scan_id"] == "scan-new"
    assert body["scans"][1]["scan_id"] == "scan-old"
    # Each row carries the basics.
    assert body["scans"][0]["type"] == "workspace"


def test_list_scans_returns_empty_list_when_dir_missing(tmp_path: Path, monkeypatch):
    from agent_readiness.live_scan.onboarding_api import list_scans

    monkeypatch.setenv("HOME", str(tmp_path))
    body, status = list_scans()
    assert status == 200
    assert body["scans"] == []
