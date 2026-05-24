"""Matcher: ontology_instance_count — minimum ratified instances of an Object Type."""

from __future__ import annotations

from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.ontology.loader import load_ontology
from agent_readiness_insights_protocol.ontology.types import LifecycleState


def match_ontology_instance_count(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    ont_dir = ctx.root / "ontology"
    if not ont_dir.is_dir():
        object_type = str(cfg["object_type"])
        minimum = int(cfg["min"])
        return [(
            None,
            None,
            f"0/{minimum} ratified {object_type} instances (no ontology/ directory)",
        )]

    object_type = str(cfg["object_type"])
    minimum = int(cfg["min"])
    state_filter = str(cfg.get("state", "ratified"))

    ont = load_ontology(ont_dir)
    instances = ont.object_instances.get(object_type, [])
    if state_filter == "ratified":
        count = sum(1 for i in instances if i.lifecycle.state == LifecycleState.RATIFIED)
    else:
        count = len(instances)

    if count >= minimum:
        return []
    return [(
        None,
        None,
        f"{count}/{minimum} ratified {object_type} instances",
    )]
