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


def _write_repo_object_type(workspace: Path) -> None:
    target = workspace / "ontology" / "objectTypes" / "Repo.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "apiVersion: agent-readiness.io/v1\n"
        "kind: ObjectType\n"
        "metadata: {name: Repo}\n"
        "spec:\n"
        "  identity:\n"
        "    fields: [name]\n"
        "    id_template: \"{{ name }}\"\n"
        "  properties:\n"
        "    - {name: name, type: string, required: true}\n"
    )


def test_validate_non_strict_does_not_enforce_closure(tmp_path: Path):
    # Closure (ratified-touches-proposed) is strict-only; non-strict tolerates
    # both endpoints existing but with mixed lifecycle.
    _write_ratified_repo(tmp_path, "a")
    _write_proposed_repo(tmp_path, "b")
    _write_ratified_link(tmp_path, "a--dependsOn--b", "a", "b")
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


# -- Check A: instance metadata.id matches rendered id_template ----------------


def test_validate_flags_id_template_mismatch(tmp_path: Path):
    _write_repo_object_type(tmp_path)
    target = tmp_path / "ontology" / "instances" / "Repo" / "alpha.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    inst = ObjectInstance(
        apiVersion="agent-readiness.io/v1",
        kind="ObjectInstance",
        metadata={"object_type": "Repo", "id": "wrong"},
        spec={"properties": {"name": "alpha"}},
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

    rep = validate_ontology(tmp_path / "ontology", strict=False)
    assert not rep.ok
    assert any(i.kind == "id_template_mismatch" for i in rep.issues)
    issue = next(i for i in rep.issues if i.kind == "id_template_mismatch")
    assert "alpha" in issue.message
    assert "wrong" in issue.message


def test_validate_passes_when_id_matches_template(tmp_path: Path):
    _write_repo_object_type(tmp_path)
    _write_ratified_repo(tmp_path, "alpha")
    rep = validate_ontology(tmp_path / "ontology", strict=False)
    assert rep.ok, [i.message for i in rep.issues]


def test_validate_skips_check_when_no_id_template(tmp_path: Path):
    target = tmp_path / "ontology" / "objectTypes" / "Repo.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "apiVersion: agent-readiness.io/v1\nkind: ObjectType\n"
        "metadata: {name: Repo}\nspec: {properties: []}\n"
    )
    _write_ratified_repo(tmp_path, "anything")
    rep = validate_ontology(tmp_path / "ontology", strict=False)
    assert rep.ok


def test_validate_flags_id_template_unresolved_when_property_missing(tmp_path: Path):
    # ObjectType template references {{ version }} but the instance doesn't set it
    target = tmp_path / "ontology" / "objectTypes" / "Protocol.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "apiVersion: agent-readiness.io/v1\nkind: ObjectType\n"
        "metadata: {name: Protocol}\n"
        "spec:\n"
        "  identity:\n"
        "    id_template: \"{{ name }}@{{ version }}\"\n"
        "  properties:\n"
        "    - {name: name, type: string, required: true}\n"
    )
    inst_path = tmp_path / "ontology" / "instances" / "Protocol" / "foo.yaml"
    inst_path.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    inst = ObjectInstance(
        apiVersion="agent-readiness.io/v1",
        kind="ObjectInstance",
        metadata={"object_type": "Protocol", "id": "foo"},
        spec={"properties": {"name": "foo"}},
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
    inst_path.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))
    rep = validate_ontology(tmp_path / "ontology", strict=False)
    assert not rep.ok
    assert any(i.kind == "id_template_unresolved" for i in rep.issues)


# -- Check B: link endpoints must resolve to an existing instance --------------


def test_validate_flags_link_to_missing_object(tmp_path: Path):
    _write_repo_object_type(tmp_path)
    _write_ratified_repo(tmp_path, "a")
    _write_ratified_link(tmp_path, "a--dependsOn--b", "a", "b")
    rep = validate_ontology(tmp_path / "ontology", strict=False)
    assert not rep.ok
    assert any(i.kind == "link_target_missing" for i in rep.issues)
    issue = next(i for i in rep.issues if i.kind == "link_target_missing")
    assert "'b'" in issue.message
    assert "a--dependsOn--b" in issue.atom_id


def test_validate_passes_when_link_targets_exist(tmp_path: Path):
    _write_repo_object_type(tmp_path)
    _write_ratified_repo(tmp_path, "a")
    _write_ratified_repo(tmp_path, "b")
    _write_ratified_link(tmp_path, "a--dependsOn--b", "a", "b")
    rep = validate_ontology(tmp_path / "ontology", strict=False)
    assert rep.ok, [i.message for i in rep.issues]


def test_validate_flags_proposed_link_to_missing_object(tmp_path: Path):
    # Check B is not gated by lifecycle — a proposed link to nothing is still broken.
    _write_repo_object_type(tmp_path)
    _write_ratified_repo(tmp_path, "a")
    target = tmp_path / "ontology" / "instances" / "dependsOn" / "a--dependsOn--ghost.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    link = LinkInstance(
        apiVersion="agent-readiness.io/v1",
        kind="LinkInstance",
        metadata={"object_type": "dependsOn", "id": "a--dependsOn--ghost"},
        spec={
            "from": {"object_type": "Repo", "id": "a"},
            "to": {"object_type": "Repo", "id": "ghost"},
        },
        lifecycle=Lifecycle(
            state=LifecycleState.PROPOSED,
            proposed_by="test",
            proposed_at=now,
            confidence=0.5,
            markers=[],
        ),
    )
    target.write_text(yaml.safe_dump(link.model_dump(mode="json"), sort_keys=False))
    rep = validate_ontology(tmp_path / "ontology", strict=False)
    assert not rep.ok
    assert any(i.kind == "link_target_missing" for i in rep.issues)
