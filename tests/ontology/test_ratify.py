from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from agent_readiness.ontology.ratify import ratify_atom
from agent_readiness_insights_protocol.ontology.types import (
    Lifecycle,
    LifecycleState,
    ObjectInstance,
)

from .bootstrap.conftest import write_ratified_repo_instance


def _write_proposed_instance(
    workspace: Path,
    repo_id: str,
    *,
    markers: list[str] | None = None,
    state: LifecycleState = LifecycleState.PROPOSED,
) -> None:
    target = workspace / "ontology" / "instances" / "Repo" / f"{repo_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    lifecycle = Lifecycle(
        state=state,
        proposed_by="test",
        proposed_at=now,
        confidence=0.9,
        markers=markers or [],
    )
    if state == LifecycleState.RATIFIED:
        lifecycle.ratified_by = "existing"
        lifecycle.ratified_at = now
    inst = ObjectInstance(
        apiVersion="agent-readiness.io/v1",
        kind="ObjectInstance",
        metadata={"object_type": "Repo", "id": repo_id},
        spec={"properties": {"name": repo_id}},
        lifecycle=lifecycle,
    )
    target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))


def test_ratify_bumps_proposed_to_ratified(tmp_path: Path):
    _write_proposed_instance(tmp_path, "my-repo")
    path = ratify_atom(tmp_path, "my-repo", "alice")
    raw = yaml.safe_load(path.read_text())
    assert raw["lifecycle"]["state"] == "ratified"
    assert raw["lifecycle"]["ratified_by"] == "alice"
    assert raw["lifecycle"]["ratified_at"]


def test_ratify_idempotent_when_already_ratified(tmp_path: Path):
    write_ratified_repo_instance(tmp_path, "my-repo")
    path = ratify_atom(tmp_path, "my-repo", "alice")
    raw = yaml.safe_load(path.read_text())
    assert raw["lifecycle"]["ratified_by"] == "test-human"


def test_ratify_rejects_unresolved_markers(tmp_path: Path):
    _write_proposed_instance(tmp_path, "my-repo", markers=["spec.properties.primary_manifest"])
    with pytest.raises(ValueError, match="unresolved markers"):
        ratify_atom(tmp_path, "my-repo", "alice")


def test_ratify_raises_lookup_for_unknown_atom(tmp_path: Path):
    (tmp_path / "ontology" / "instances").mkdir(parents=True)
    with pytest.raises(LookupError, match="Atom not found"):
        ratify_atom(tmp_path, "missing", "alice")
