from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_readiness.ontology.validate import validate_ontology
from agent_readiness_insights_protocol.ontology.types import (
    Lifecycle,
    LifecycleState,
    LinkInstance,
    ObjectInstance,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_ratified_repo(workspace: Path, repo_id: str) -> None:
    target = workspace / "ontology" / "instances" / "Repo" / f"{repo_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    inst = ObjectInstance(
        apiVersion="agent-readiness.io/v1",
        kind="ObjectInstance",
        metadata={"object_type": "Repo", "id": repo_id},
        spec={"properties": {"name": repo_id}},
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
    target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))


def _write_proposed_repo(workspace: Path, repo_id: str) -> None:
    target = workspace / "ontology" / "instances" / "Repo" / f"{repo_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
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
    target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))


def _write_ratified_link(
    workspace: Path,
    link_id: str,
    from_id: str,
    to_id: str,
) -> None:
    target = workspace / "ontology" / "instances" / "dependsOn" / f"{link_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
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


def test_validate_non_strict_always_ok(tmp_path: Path):
    _write_ratified_link(tmp_path, "a--dependsOn--b", "a", "unratified-b")
    rep = validate_ontology(tmp_path / "ontology", strict=False)
    assert rep.ok


def test_validate_strict_clean_when_endpoints_ratified(tmp_path: Path):
    _write_ratified_repo(tmp_path, "a")
    _write_ratified_repo(tmp_path, "b")
    _write_ratified_link(tmp_path, "a--dependsOn--b", "a", "b")
    rep = validate_ontology(tmp_path / "ontology", strict=True)
    assert rep.ok
    assert rep.issues == []


def test_validate_strict_flags_closure_violation(tmp_path: Path):
    _write_ratified_repo(tmp_path, "a")
    _write_proposed_repo(tmp_path, "b")
    _write_ratified_link(tmp_path, "a--dependsOn--b", "a", "b")
    rep = validate_ontology(tmp_path / "ontology", strict=True)
    assert not rep.ok
    assert len(rep.issues) == 1
    assert rep.issues[0].kind == "closure_violation"
