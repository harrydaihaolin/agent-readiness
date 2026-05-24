"""Matcher: ontology_ref_closure — ratified Link endpoints resolve to ratified objects."""

from __future__ import annotations

from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.ontology.loader import load_ontology
from agent_readiness_insights_protocol.ontology.types import LifecycleState


def match_ontology_ref_closure(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    ont_dir = ctx.root / "ontology"
    if not ont_dir.is_dir():
        return []

    ont = load_ontology(ont_dir)
    ratified_obj_ids: set[str] = set()
    for insts in ont.object_instances.values():
        for inst in insts:
            if inst.lifecycle.state == LifecycleState.RATIFIED:
                ratified_obj_ids.add(str(inst.metadata.get("id", "")))

    findings: list[tuple[str | None, int | None, str]] = []
    for insts in ont.link_instances.values():
        for link in insts:
            if link.lifecycle.state != LifecycleState.RATIFIED:
                continue
            link_id = str(link.metadata.get("id", "<unknown>"))
            spec = link.spec or {}
            for end in ("from", "to"):
                endpoint = spec.get(end) or {}
                target_id = endpoint.get("id")
                if target_id and target_id not in ratified_obj_ids:
                    obj_type = endpoint.get("object_type", "?")
                    findings.append((
                        None,
                        None,
                        (
                            f"Dangling reference in ratified link {link_id}: "
                            f"{end} {obj_type} '{target_id}' is missing or not ratified"
                        ),
                    ))
    return findings
