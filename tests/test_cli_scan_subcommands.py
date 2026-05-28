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
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
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
