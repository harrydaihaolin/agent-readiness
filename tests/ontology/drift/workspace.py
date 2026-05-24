"""Drift workspace builder for tests."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_readiness_insights_protocol.ontology.types import Lifecycle, LifecycleState, ObjectInstance


def _init_git_repo(
    repo_path: Path,
    *,
    with_pyproject: bool = True,
    with_package_json: bool = False,
) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo_path, check=True)
    subprocess.run(["git", "-C", str(repo_path), "config", "user.email", "test@test"], check=True)
    subprocess.run(["git", "-C", str(repo_path), "config", "user.name", "test"], check=True)
    if with_pyproject:
        (repo_path / "pyproject.toml").write_text("[project]\nname = \"test\"\n")
    if with_package_json:
        (repo_path / "package.json").write_text('{"name": "test"}')


def _ratified_lifecycle() -> Lifecycle:
    now = datetime.now(timezone.utc).isoformat()
    return Lifecycle(
        state=LifecycleState.RATIFIED,
        proposed_by="test",
        proposed_at=now,
        confidence=1.0,
        markers=[],
        ratified_by="test-human",
        ratified_at=now,
    )


def _write_ratified_repo_instance(
    workspace: Path,
    repo_id: str,
    *,
    primary_manifest: str = "pyproject.toml",
    languages: list[str] | None = None,
    name: str | None = None,
) -> None:
    target = workspace / "ontology" / "instances" / "Repo" / f"{repo_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    inst = ObjectInstance(
        apiVersion="agent-readiness.io/v1",
        kind="ObjectInstance",
        metadata={"object_type": "Repo", "id": repo_id},
        spec={
            "properties": {
                "name": name or repo_id,
                "languages": languages or ["python"],
                "primary_manifest": primary_manifest,
            }
        },
        lifecycle=_ratified_lifecycle(),
    )
    target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))


def build_drift_workspace(root: Path) -> Path:
    """Materialize a workspace with ratified ontology + induced drift."""
    repo_type = root / "ontology" / "objectTypes" / "Repo.yaml"
    repo_type.parent.mkdir(parents=True, exist_ok=True)
    repo_type.write_text(
        "apiVersion: agent-readiness.io/v1\n"
        "kind: ObjectType\n"
        "metadata:\n"
        "  name: Repo\n"
        "spec:\n"
        "  properties: []\n"
    )

    _write_ratified_repo_instance(root, "repo-a")
    _write_ratified_repo_instance(root, "repo-b", name="repo-b-renamed")
    _write_ratified_repo_instance(root, "repo-c")

    _init_git_repo(root / "repo-b-renamed")
    _init_git_repo(root / "repo-c", with_package_json=True)
    _init_git_repo(root / "repo-d")

    return root
