"""Tests for the new typed scan CLI subcommands (plan 2)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _git_init(path: Path) -> None:
    (path / ".git").mkdir(parents=True, exist_ok=True)


@pytest.fixture
def workspace_with_two_repos(tmp_path: Path) -> Path:
    (tmp_path / "alpha").mkdir()
    _git_init(tmp_path / "alpha")
    (tmp_path / "beta").mkdir()
    _git_init(tmp_path / "beta")
    return tmp_path


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parents[1] / "src")
    # Preserve the runner's full import path (editable deps, user-site) when
    # tests redirect HOME for onboarding path_for().
    env["PYTHONPATH"] = os.pathsep.join(
        dict.fromkeys([src, *sys.path, env.get("PYTHONPATH", "")])
    )
    return subprocess.run(
        [sys.executable, "-m", "agent_readiness.cli", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
    )


def test_inspect_json_output_has_enumeration_and_classification(workspace_with_two_repos: Path):
    proc = _run_cli(["inspect", str(workspace_with_two_repos), "--json"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "enumeration" in payload
    assert "classification" in payload
    assert payload["classification"]["suggested_type"] == "workspace"
    assert len(payload["enumeration"]["repos"]) == 2


def test_inspect_human_readable_output_summarizes(workspace_with_two_repos: Path):
    proc = _run_cli(["inspect", str(workspace_with_two_repos)])
    assert proc.returncode == 0, proc.stderr
    # Must mention the count, type, and confidence.
    assert "2" in proc.stdout
    assert "workspace" in proc.stdout.lower()
    assert "medium" in proc.stdout.lower()


def test_inspect_nonexistent_path_exits_nonzero(tmp_path: Path):
    proc = _run_cli(["inspect", str(tmp_path / "missing")])
    assert proc.returncode != 0
    assert "not" in proc.stderr.lower() or "no" in proc.stderr.lower()


def test_launch_dashboard_writes_onboarding_json(tmp_path: Path, monkeypatch):
    """The shared helper must persist OnboardingState with committed_type
    set from the caller, before returning the URL."""
    from datetime import datetime, timezone

    monkeypatch.setenv("HOME", str(tmp_path))

    # Import inside the test so monkeypatch takes effect.
    from agent_readiness import cli as cli_mod
    from agent_readiness.onboarding import load, path_for

    target = tmp_path / "demo"
    target.mkdir()
    (target / ".git").mkdir()

    result = cli_mod._launch_dashboard_with_onboarding(
        path=target,
        committed_type="single_repo",
        now=datetime(2026, 5, 27, 15, 0, 0, tzinfo=timezone.utc),
        no_open=True,
    )
    assert result["status"] == "onboarding_required"
    assert result["dashboard_url"].endswith(f"/#/onboarding/{result['scan_id']}")
    assert result["type"] == "single_repo"

    state = load(path_for(result["scan_id"]))
    assert state is not None
    assert state.committed_type == "single_repo"
    assert state.classification.suggested_type == "single_repo"
    assert state.selection is None  # not committed yet


def test_scan_repo_prints_onboarding_url_in_json(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "demo"
    target.mkdir()
    (target / ".git").mkdir()

    proc = _run_cli(["scan-repo", str(target), "--json", "--no-open"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "onboarding_required"
    assert payload["type"] == "single_repo"
    assert "/onboarding/" in payload["dashboard_url"]


def test_scan_monorepo_emits_committed_type_monorepo(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "demo"
    target.mkdir()
    (target / ".git").mkdir()
    (target / "pkg-a").mkdir()
    (target / "pkg-a" / ".git").mkdir()

    proc = _run_cli(["scan-monorepo", str(target), "--json", "--no-open"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["type"] == "monorepo"


def test_scan_workspace_emits_committed_type_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "demo"
    target.mkdir()
    (target / "alpha").mkdir()
    (target / "alpha" / ".git").mkdir()
    (target / "beta").mkdir()
    (target / "beta" / ".git").mkdir()

    proc = _run_cli(["scan-workspace", str(target), "--json", "--no-open"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["type"] == "workspace"


def test_scan_and_view_prints_deprecation_warning(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "demo"
    target.mkdir()
    (target / "alpha").mkdir()
    (target / "alpha" / ".git").mkdir()

    proc = _run_cli(["scan-and-view", str(target), "--json", "--no-open"])
    # Should still succeed.
    assert proc.returncode == 0, proc.stderr
    # Warning must mention the replacement.
    assert "deprecated" in proc.stderr.lower()
    assert "scan-workspace" in proc.stderr or "scan-repo" in proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "onboarding_required"
