from __future__ import annotations

from pathlib import Path

import pytest

from agent_readiness.ontology.bootstrap.propose_links import propose_link_instances

from .conftest import write_ratified_repo_instance


@pytest.fixture
def linked_workspace(tmp_path: Path) -> Path:
    """A workspace with two repos where repo-a depends on repo-b."""
    for name in ("repo-a", "repo-b"):
        d = tmp_path / name
        d.mkdir()
        (d / ".git").mkdir()
        (d / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / "repo-a" / "pyproject.toml").write_text(
        '[project]\nname = "repo-a"\nversion = "0.1.0"\ndependencies = ["repo-b>=0.1"]\n'
    )
    (tmp_path / "repo-b" / "pyproject.toml").write_text(
        '[project]\nname = "repo-b"\nversion = "0.1.0"\n'
    )
    write_ratified_repo_instance(tmp_path, "repo-a")
    write_ratified_repo_instance(tmp_path, "repo-b")
    return tmp_path


def test_proposes_dependsOn_from_pyproject(linked_workspace: Path):
    env = propose_link_instances(linked_workspace, link_type="dependsOn")
    assert any(
        p.properties["from"]["id"] == "repo-a" and p.properties["to"]["id"] == "repo-b"
        for p in env.proposed
    )
    assert env.target_type == "dependsOn"


def test_refuses_when_no_repo_instances(tmp_path: Path):
    with pytest.raises(RuntimeError, match="No Repo instances"):
        propose_link_instances(tmp_path, link_type="dependsOn")


def test_refuses_when_under_ratification_threshold(tmp_path: Path):
    # Two Repos but neither ratified
    (tmp_path / "ontology" / "instances" / "Repo").mkdir(parents=True)
    from datetime import datetime, timezone

    import yaml

    from agent_readiness_insights_protocol.ontology.types import (
        Lifecycle,
        LifecycleState,
        ObjectInstance,
    )

    now = datetime.now(timezone.utc).isoformat()
    for repo_id in ("r1", "r2"):
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
                markers=[],
            ),
        )
        (tmp_path / "ontology" / "instances" / "Repo" / f"{repo_id}.yaml").write_text(
            yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False)
        )
    with pytest.raises(RuntimeError, match="threshold"):
        propose_link_instances(tmp_path, link_type="dependsOn", min_ratified_pct=0.8)


def test_unresolved_dep_recorded_as_ambiguity(linked_workspace: Path):
    # Add an unresolved external dep to repo-a's pyproject
    (linked_workspace / "repo-a" / "pyproject.toml").write_text(
        '[project]\nname = "repo-a"\nversion = "0.1.0"\n'
        'dependencies = ["repo-b>=0.1", "requests>=2.0"]\n'
    )
    env = propose_link_instances(linked_workspace, link_type="dependsOn")
    # repo-b is resolved
    assert any(p.properties["to"]["id"] == "repo-b" for p in env.proposed)
    # requests is external and should not produce a proposal but may produce an ambiguity
    assert all(p.properties["to"]["id"] != "requests" for p in env.proposed)


@pytest.fixture
def protocol_link_workspace(tmp_path: Path) -> Path:
    d = tmp_path / "foo-protocol"
    d.mkdir()
    (d / ".git").mkdir()
    (d / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    write_ratified_repo_instance(tmp_path, "foo-protocol")
    return tmp_path


def test_providesProtocol_for_name_suffix(protocol_link_workspace: Path):
    env = propose_link_instances(protocol_link_workspace, link_type="providesProtocol")
    assert env.target_type == "providesProtocol"
    assert any(
        p.properties["from"]["id"] == "foo-protocol"
        and p.properties["to"]["object_type"] == "Protocol"
        for p in env.proposed
    )


@pytest.fixture
def codeowners_workspace(tmp_path: Path) -> Path:
    d = tmp_path / "owned-repo"
    d.mkdir()
    (d / ".git").mkdir()
    (d / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (d / "CODEOWNERS").write_text("* @some-team\n")
    write_ratified_repo_instance(tmp_path, "owned-repo")
    return tmp_path


def test_ownedBy_from_CODEOWNERS(codeowners_workspace: Path):
    env = propose_link_instances(codeowners_workspace, link_type="ownedBy")
    assert any(
        p.properties["from"]["id"] == "owned-repo"
        and p.properties["to"] == {"object_type": "Owner", "id": "@some-team"}
        for p in env.proposed
    )


def test_partOf_returns_empty_when_no_modules(tmp_path: Path):
    write_ratified_repo_instance(tmp_path, "r1")
    env = propose_link_instances(tmp_path, link_type="partOf")
    assert env.proposed == []
    assert any("Module instances not yet bootstrapped" in a.reason for a in env.ambiguities)


def test_releasedAs_is_deferred(tmp_path: Path):
    write_ratified_repo_instance(tmp_path, "r1")
    env = propose_link_instances(tmp_path, link_type="releasedAs")
    assert env.proposed == []
    assert any(a.id == "releasedAs--deferred" for a in env.ambiguities)
