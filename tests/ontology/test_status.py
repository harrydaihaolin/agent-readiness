from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_readiness.ontology.status import status_ontology
from agent_readiness_insights_protocol.ontology.types import (
    Lifecycle,
    LifecycleState,
    ObjectInstance,
)

from .bootstrap.conftest import write_ratified_repo_instance


def _write_proposed_repo(workspace: Path, repo_id: str) -> None:
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
            markers=[],
        ),
    )
    target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))


def test_status_counts_proposed_and_ratified(tmp_path: Path):
    # Seed object type declaration
    ont_root = tmp_path / "ontology"
    type_src = Path(__file__).parent.parent / "fixtures" / "ontology_minimal" / "ontology"
    (ont_root / "objectTypes").mkdir(parents=True)
    (ont_root / "objectTypes" / "Repo.yaml").write_text(
        (type_src / "objectTypes" / "Repo.yaml").read_text()
    )

    write_ratified_repo_instance(tmp_path, "ratified-one")
    _write_proposed_repo(tmp_path, "proposed-one")

    rep = status_ontology(ont_root)
    ts = rep.object_types["Repo"]
    assert ts.declared == 1
    assert ts.ratified_instances == 1
    assert ts.proposed_instances == 1


def test_status_empty_ontology(tmp_path: Path):
    (tmp_path / "ontology").mkdir()
    rep = status_ontology(tmp_path / "ontology")
    assert rep.object_types == {}
    assert rep.interfaces_declared == 0
