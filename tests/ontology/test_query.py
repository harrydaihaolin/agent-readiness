from __future__ import annotations

from pathlib import Path

import pytest

from agent_readiness.ontology.query import query_ontology

from .bootstrap.conftest import write_ratified_repo_instance


def test_count_returns_instance_total(tmp_path: Path):
    write_ratified_repo_instance(tmp_path, "repo-a")
    write_ratified_repo_instance(tmp_path, "repo-b")
    assert query_ontology(tmp_path / "ontology", "count(Repo)") == 2


def test_list_returns_atom_ids(tmp_path: Path):
    write_ratified_repo_instance(tmp_path, "repo-a")
    write_ratified_repo_instance(tmp_path, "repo-b")
    ids = query_ontology(tmp_path / "ontology", "list(Repo)")
    assert sorted(ids) == ["repo-a", "repo-b"]


def test_links_returns_touching_link_instances(tmp_path: Path):
    from datetime import datetime, timezone

    import yaml

    from agent_readiness_insights_protocol.ontology.types import (
        Lifecycle,
        LifecycleState,
        LinkInstance,
    )

    write_ratified_repo_instance(tmp_path, "repo-a")
    write_ratified_repo_instance(tmp_path, "repo-b")
    now = datetime.now(timezone.utc).isoformat()
    link = LinkInstance(
        apiVersion="agent-readiness.io/v1",
        kind="LinkInstance",
        metadata={"object_type": "dependsOn", "id": "repo-a--dependsOn--repo-b"},
        spec={
            "from": {"object_type": "Repo", "id": "repo-a"},
            "to": {"object_type": "Repo", "id": "repo-b"},
        },
        lifecycle=Lifecycle(
            state=LifecycleState.PROPOSED,
            proposed_by="test",
            proposed_at=now,
            confidence=1.0,
            markers=[],
        ),
    )
    link_path = tmp_path / "ontology" / "instances" / "dependsOn" / "link.yaml"
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.write_text(yaml.safe_dump(link.model_dump(mode="json"), sort_keys=False))

    hits = query_ontology(tmp_path / "ontology", "links(Repo:repo-a)")
    assert len(hits) == 1
    assert hits[0]["link_type"] == "dependsOn"
    assert hits[0]["from"]["id"] == "repo-a"


def test_unsupported_query_raises(tmp_path: Path):
    (tmp_path / "ontology").mkdir()
    with pytest.raises(ValueError, match="Unsupported query"):
        query_ontology(tmp_path / "ontology", "bad()")
