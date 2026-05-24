"""Shared helpers for ontology matcher tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_readiness_insights_protocol.ontology.types import (
    Lifecycle,
    LifecycleState,
    LinkInstance,
    ObjectInstance,
)


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


def scaffold_ratified_ontology(
    workspace: Path,
    *,
    repos: list[str] | None = None,
    links: list[tuple[str, str, str]] | None = None,
) -> None:
    """Build a minimal ontology/ tree with ratified Repo and Link instances."""
    repos = repos or []
    links = links or []
    for repo_id in repos:
        target = workspace / "ontology" / "instances" / "Repo" / f"{repo_id}.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        inst = ObjectInstance(
            apiVersion="agent-readiness.io/v1",
            kind="ObjectInstance",
            metadata={"object_type": "Repo", "id": repo_id},
            spec={"properties": {"name": repo_id}},
            lifecycle=_ratified_lifecycle(),
        )
        target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))

    for from_id, to_id, link_type in links:
        link_id = f"{from_id}--{link_type}--{to_id}"
        target = workspace / "ontology" / "instances" / link_type / f"{link_id}.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        link = LinkInstance(
            apiVersion="agent-readiness.io/v1",
            kind="LinkInstance",
            metadata={"object_type": link_type, "id": link_id},
            spec={
                "from": {"object_type": "Repo", "id": from_id},
                "to": {"object_type": "Repo", "id": to_id},
            },
            lifecycle=_ratified_lifecycle(),
        )
        target.write_text(yaml.safe_dump(link.model_dump(mode="json"), sort_keys=False))
