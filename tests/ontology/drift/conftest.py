"""Shared fixtures for ontology drift tests."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.ontology.drift.workspace import _write_ratified_repo_instance, build_drift_workspace


@pytest.fixture
def fixture_drift_workspace(tmp_path: Path) -> Path:
    return build_drift_workspace(tmp_path / "workspace")


@pytest.fixture
def fake_manifest_git_repo(tmp_path: Path) -> Path:
    manifest = tmp_path / "manifest-repo"
    manifest.mkdir()
    instances = manifest / "ontology" / "instances" / "Repo"
    instances.mkdir(parents=True)

    for repo_id in ("repo-a", "repo-b", "repo-c"):
        _write_ratified_repo_instance(
            manifest,
            repo_id,
            name="repo-b-renamed" if repo_id == "repo-b" else None,
        )

    subprocess.run(["git", "init", "-q"], cwd=manifest, check=True)
    subprocess.run(["git", "-C", str(manifest), "config", "user.email", "test@test"], check=True)
    subprocess.run(["git", "-C", str(manifest), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(manifest), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(manifest), "commit", "-m", "baseline ontology"], check=True)
    return manifest
