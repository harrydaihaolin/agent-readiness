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
