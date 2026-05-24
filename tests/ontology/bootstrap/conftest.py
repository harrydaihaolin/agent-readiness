from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_readiness_insights_protocol.ontology.types import Lifecycle, LifecycleState, ObjectInstance


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


def write_ratified_repo_instance(workspace: Path, repo_id: str, primary_manifest: str = "pyproject.toml") -> None:
    """Materialize a ratified Repo ObjectInstance YAML in workspace/ontology/instances/Repo/."""
    target = workspace / "ontology" / "instances" / "Repo" / f"{repo_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    inst = ObjectInstance(
        apiVersion="agent-readiness.io/v1",
        kind="ObjectInstance",
        metadata={"object_type": "Repo", "id": repo_id},
        spec={
            "properties": {
                "name": repo_id,
                "languages": ["python"],
                "primary_manifest": primary_manifest,
            }
        },
        lifecycle=_ratified_lifecycle(),
    )
    target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))
