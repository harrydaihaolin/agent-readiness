"""CLI tests for ontology drift commands."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.ontology.drift.workspace import build_drift_workspace


@pytest.fixture
def drift_workspace(tmp_path: Path) -> Path:
    return build_drift_workspace(tmp_path / "workspace")


def test_drift_cli_returns_nonzero_on_drift(drift_workspace: Path):
    result = subprocess.run(
        ["agent-readiness", "ontology", "drift", str(drift_workspace), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["severity_level"] == "warn"


def test_drift_cli_block_threshold_exit_2(drift_workspace: Path):
    result = subprocess.run(
        [
            "agent-readiness",
            "ontology",
            "drift",
            str(drift_workspace),
            "--block-threshold",
            "10",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


def test_drift_propose_pr_dry_run(drift_workspace: Path, tmp_path: Path):
    manifest = tmp_path / "manifest"
    manifest.mkdir()
    result = subprocess.run(
        [
            "agent-readiness",
            "ontology",
            "drift-propose-pr",
            str(drift_workspace),
            "--manifest",
            str(manifest),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["yaml_diff"]
    assert payload["pr_url"] is None
