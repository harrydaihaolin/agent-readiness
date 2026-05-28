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
