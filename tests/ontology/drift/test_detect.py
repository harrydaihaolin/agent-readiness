"""Tests for ontology drift detection."""
from __future__ import annotations

from agent_readiness.ontology.drift.detect import detect_drift


def test_detects_removed_repo(fixture_drift_workspace):
    report = detect_drift(fixture_drift_workspace)
    removed_ids = {d.atom_id for d in report.deltas if d.kind.value == "removed"}
    assert "repo-a" in removed_ids


def test_detects_added_repo(fixture_drift_workspace):
    report = detect_drift(fixture_drift_workspace)
    added_ids = {d.atom_id for d in report.deltas if d.kind.value == "added"}
    assert "repo-d" in added_ids


def test_detects_renamed_by_property_match(fixture_drift_workspace):
    report = detect_drift(fixture_drift_workspace)
    renamed = [d for d in report.deltas if d.kind.value == "renamed"]
    assert any(d.atom_id == "repo-b" and d.new_id == "repo-b-renamed" for d in renamed)


def test_detects_changed_properties(fixture_drift_workspace):
    report = detect_drift(fixture_drift_workspace)
    changed = [d for d in report.deltas if d.kind.value == "changed"]
    assert any(d.atom_id == "repo-c" and "languages" in d.changed_properties for d in changed)


def test_severity_threshold_warn(fixture_drift_workspace):
    report = detect_drift(fixture_drift_workspace)
    assert report.severity_level == "warn"
