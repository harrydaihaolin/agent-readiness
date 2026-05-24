from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_readiness_insights_protocol.ontology.types import (
    Lifecycle,
    LifecycleState,
    LinkInstance,
    ObjectInstance,
)

MANIFEST_TEMPLATE = Path(
    "/Users/haolin.dai/Documents/agent-readiness_project/agent-readiness-manifest/exemplar/ontology"
)

_SRC = Path(__file__).resolve().parent.parent / "src"
ENV = {"PYTHONPATH": str(_SRC), "PATH": os.environ.get("PATH", "")}


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agent_readiness.cli", *args],
        capture_output=True,
        text=True,
        env=ENV,
        cwd=cwd,
    )


def _init_workspace(tmp_path: Path) -> None:
    result = _run(
        "ontology",
        "bootstrap",
        "init",
        str(tmp_path),
        "--json",
        "--manifest-template",
        str(MANIFEST_TEMPLATE),
    )
    assert result.returncode == 0, result.stderr


def _write_proposed_repo(workspace: Path, repo_id: str, markers: list[str] | None = None) -> None:
    target = workspace / "ontology" / "instances" / "Repo" / f"{repo_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    inst = ObjectInstance(
        apiVersion="agent-readiness.io/v1",
        kind="ObjectInstance",
        metadata={"object_type": "Repo", "id": repo_id},
        spec={"properties": {"name": repo_id}},
        lifecycle=Lifecycle(
            state=LifecycleState.PROPOSED,
            proposed_by="test",
            proposed_at=now,
            confidence=0.9,
            markers=markers or [],
        ),
    )
    target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))


def _write_ratified_link(workspace: Path, link_id: str, from_id: str, to_id: str) -> None:
    target = workspace / "ontology" / "instances" / "dependsOn" / f"{link_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    link = LinkInstance(
        apiVersion="agent-readiness.io/v1",
        kind="LinkInstance",
        metadata={"object_type": "dependsOn", "id": link_id},
        spec={
            "from": {"object_type": "Repo", "id": from_id},
            "to": {"object_type": "Repo", "id": to_id},
        },
        lifecycle=Lifecycle(
            state=LifecycleState.RATIFIED,
            proposed_by="test",
            proposed_at=now,
            confidence=1.0,
            markers=[],
            ratified_by="test",
            ratified_at=now,
        ),
    )
    target.write_text(yaml.safe_dump(link.model_dump(mode="json"), sort_keys=False))


def test_bootstrap_init_success(tmp_path: Path):
    result = _run(
        "ontology",
        "bootstrap",
        "init",
        str(tmp_path),
        "--json",
        "--manifest-template",
        str(MANIFEST_TEMPLATE),
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["profile"] == "workspace"
    assert payload["files_written"] >= 25
    assert (tmp_path / "ontology" / "objectTypes" / "Repo.yaml").exists()


def test_bootstrap_init_exit_1_on_overwrite(tmp_path: Path):
    _init_workspace(tmp_path)
    result = _run(
        "ontology",
        "bootstrap",
        "init",
        str(tmp_path),
        "--manifest-template",
        str(MANIFEST_TEMPLATE),
    )
    assert result.returncode == 1
    assert "error:" in result.stderr


def test_bootstrap_init_exit_2_on_bad_profile(tmp_path: Path):
    result = _run(
        "ontology",
        "bootstrap",
        "init",
        str(tmp_path),
        "--profile",
        "bogus",
        "--manifest-template",
        str(MANIFEST_TEMPLATE),
    )
    assert result.returncode == 2
    assert "bogus" in result.stderr


def test_bootstrap_propose_objects_repo_success(tmp_path: Path):
    repo = tmp_path / "my-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / "pyproject.toml").write_text('[project]\nname = "my-repo"\nversion = "0.1.0"\n')

    result = _run(
        "ontology",
        "bootstrap",
        "propose-objects",
        str(tmp_path),
        "--object-type",
        "Repo",
        "--json",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["target_type"] == "Repo"
    assert any(p["id"] == "my-repo" for p in payload["proposed"])


def test_bootstrap_propose_objects_exit_2_bogus_type(tmp_path: Path):
    result = _run(
        "ontology",
        "bootstrap",
        "propose-objects",
        str(tmp_path),
        "--object-type",
        "BogusType",
    )
    assert result.returncode == 2
    assert "error:" in result.stderr


def test_bootstrap_propose_links_exit_2_threshold_unmet(tmp_path: Path):
    _write_proposed_repo(tmp_path, "r1")
    _write_proposed_repo(tmp_path, "r2")
    result = _run(
        "ontology",
        "bootstrap",
        "propose-links",
        str(tmp_path),
        "--link-type",
        "dependsOn",
    )
    assert result.returncode == 2
    assert "error:" in result.stderr


def test_validate_exit_0_clean(tmp_path: Path):
    _init_workspace(tmp_path)
    result = _run(
        "ontology",
        "validate",
        str(tmp_path / "ontology"),
        "--json",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_validate_exit_1_strict_closure_violation(tmp_path: Path):
    _init_workspace(tmp_path)
    from tests.ontology.bootstrap.conftest import write_ratified_repo_instance

    write_ratified_repo_instance(tmp_path, "a")
    _write_proposed_repo(tmp_path, "b")
    _write_ratified_link(tmp_path, "a--dependsOn--b", "a", "b")

    result = _run(
        "ontology",
        "validate",
        str(tmp_path / "ontology"),
        "--strict",
        "--json",
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["issues"][0]["kind"] == "closure_violation"


def test_query_count_repo(tmp_path: Path):
    from tests.ontology.bootstrap.conftest import write_ratified_repo_instance

    write_ratified_repo_instance(tmp_path, "repo-a")
    write_ratified_repo_instance(tmp_path, "repo-b")

    result = _run(
        "ontology",
        "query",
        "count(Repo)",
        "--workspace",
        str(tmp_path),
        "--json",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["result"] == 2


def test_status_returns_per_type_dict(tmp_path: Path):
    _init_workspace(tmp_path)
    from tests.ontology.bootstrap.conftest import write_ratified_repo_instance

    write_ratified_repo_instance(tmp_path, "repo-a")

    result = _run(
        "ontology",
        "status",
        str(tmp_path / "ontology"),
        "--json",
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "Repo" in payload["object_types"]
    assert payload["object_types"]["Repo"]["ratified"] == 1


def test_ratify_unknown_atom_exit_1(tmp_path: Path):
    (tmp_path / "ontology" / "instances").mkdir(parents=True)
    result = _run(
        "ontology",
        "ratify",
        "missing-id",
        "--ratified-by",
        "alice",
        "--workspace",
        str(tmp_path),
    )
    assert result.returncode == 1
    assert "error:" in result.stderr


def test_ratify_rejects_markers_exit_2(tmp_path: Path):
    _write_proposed_repo(tmp_path, "marked-repo", markers=["spec.properties.primary_manifest"])
    result = _run(
        "ontology",
        "ratify",
        "marked-repo",
        "--ratified-by",
        "alice",
        "--workspace",
        str(tmp_path),
    )
    assert result.returncode == 2
    assert "error:" in result.stderr


def test_ontology_help_lists_all_subcommands():
    result = _run("ontology", "--help")
    assert result.returncode == 0
    help_text = result.stdout
    for cmd in (
        "bootstrap",
        "load",
        "ratify",
        "validate",
        "query",
        "status",
    ):
        assert cmd in help_text

    bootstrap_help = _run("ontology", "bootstrap", "--help")
    assert bootstrap_help.returncode == 0
    for cmd in (
        "init",
        "propose-objects",
        "propose-links",
        "propose-interfaces",
        "propose-functions",
        "propose-actions",
    ):
        assert cmd in bootstrap_help.stdout
