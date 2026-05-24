"""Matcher: ontology_interface_satisfaction — no failing Interface claims on ratified objects."""

from __future__ import annotations

from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.ontology.loader import load_ontology
from agent_readiness_insights_protocol.ontology.types import LifecycleState


def match_ontology_interface_satisfaction(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    ont_dir = ctx.root / "ontology"
    if not ont_dir.is_dir():
        return []

    scope = {str(n) for n in cfg.get("interfaces", [])}
    ont = load_ontology(ont_dir)
    findings: list[tuple[str | None, int | None, str]] = []

    for insts in ont.object_instances.values():
        for inst in insts:
            if inst.lifecycle.state != LifecycleState.RATIFIED:
                continue
            repo_id = str(inst.metadata.get("id", "<unknown>"))
            claims = (inst.spec or {}).get("implements") or []
            if not isinstance(claims, list):
                continue
            for claim in claims:
                if not isinstance(claim, dict):
                    continue
                iface = str(claim.get("interface", ""))
                if scope and iface not in scope:
                    continue
                if claim.get("satisfaction") == "failing":
                    findings.append((
                        None,
                        None,
                        f"Interface claim failing: ({repo_id}, {iface})",
                    ))
    return findings
