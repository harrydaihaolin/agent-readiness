"""Tests for OnboardingState disk persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest


NOW = datetime(2026, 5, 27, 15, 0, 0, tzinfo=timezone.utc)


def _make_state(scan_dir: Path, scan_id: str = "scan-1"):
    from agent_readiness.onboarding import (
        EnumerationResult,
        OnboardingClassification,
        OnboardingState,
    )

    return OnboardingState(
        scan_id=scan_id,
        committed_type="workspace",
        enumeration=EnumerationResult(
            root=str(scan_dir),
            root_has_git=False,
            repos=[],
            directories_walked=10,
            elapsed_ms=5,
        ),
        classification=OnboardingClassification(
            suggested_type="workspace",
            confidence="medium",
            rationale="x",
        ),
        selection=None,
        created_at=NOW,
    )


def test_save_then_load_round_trips(tmp_path: Path):
    from agent_readiness.onboarding import load, save

    state = _make_state(tmp_path)
    save(tmp_path, state)
    loaded = load(tmp_path)
    assert loaded == state


def test_load_returns_none_when_file_missing(tmp_path: Path):
    from agent_readiness.onboarding import load

    assert load(tmp_path) is None


def test_save_is_atomic_no_partial_file_on_error(tmp_path: Path, monkeypatch):
    """Atomic rename — interrupted writes must not leave a half-baked
    onboarding.json that fails to parse on reload."""
    from agent_readiness import onboarding
    from agent_readiness.onboarding import save

    state = _make_state(tmp_path)

    # Force the final rename to fail; verify no half-baked file is left.
    real_replace = onboarding.os.replace

    def bad_replace(*a, **kw):
        raise OSError("boom")

    monkeypatch.setattr(onboarding.os, "replace", bad_replace)
    with pytest.raises(OSError):
        save(tmp_path, state)

    # No onboarding.json should exist after the failed save.
    assert not (tmp_path / "onboarding.json").exists()
    # No leftover tmp file should remain.
    tmp_files = list(tmp_path.glob("onboarding.json.*"))
    assert tmp_files == []

    monkeypatch.setattr(onboarding.os, "replace", real_replace)


def test_commit_selection_creates_selection_at_revision_1(tmp_path: Path):
    from agent_readiness.onboarding import commit_selection, load, save

    save(tmp_path, _make_state(tmp_path))
    new_state = commit_selection(
        tmp_path,
        type="workspace",
        selected_paths=["a", "b"],
        committed_at=NOW,
    )
    assert new_state.selection is not None
    assert new_state.selection.revision == 1
    assert new_state.selection.selected_paths == ["a", "b"]
    assert load(tmp_path).selection.revision == 1


def test_commit_selection_bumps_revision_on_reconfigure(tmp_path: Path):
    from agent_readiness.onboarding import commit_selection, save

    save(tmp_path, _make_state(tmp_path))
    commit_selection(tmp_path, type="workspace", selected_paths=["a"], committed_at=NOW)
    after = commit_selection(tmp_path, type="workspace", selected_paths=["a", "b"], committed_at=NOW)
    assert after.selection.revision == 2


def test_commit_selection_updates_committed_type(tmp_path: Path):
    """User can switch type via the Detected page's 'Switch type' side path."""
    from agent_readiness.onboarding import commit_selection, save

    save(tmp_path, _make_state(tmp_path))
    after = commit_selection(
        tmp_path,
        type="monorepo",  # different from the original committed_type=workspace
        selected_paths=["pkg-a"],
        committed_at=NOW,
    )
    assert after.committed_type == "monorepo"
    assert after.selection.type == "monorepo"


def test_path_for_scan_id_resolves_under_home_dir(tmp_path: Path, monkeypatch):
    from agent_readiness import onboarding

    monkeypatch.setenv("HOME", str(tmp_path))
    p = onboarding.path_for("scan-xyz")
    assert p == tmp_path / ".agent-readiness" / "scans" / "scan-xyz"
