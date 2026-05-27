"""Inference: a repo cannot ``dependsOn`` itself.

The ``dependsOn`` LinkType declares ``axioms.irreflexive: true``.
A self-loop here usually means a ratification slipped past the
human reviewer (the bootstrap proposers refuse to emit reflexive
edges). Catching it as a derived fact gives the agent a one-shot
remediation path without re-reading the manifest YAML by hand.
"""

from __future__ import annotations

from agent_readiness.ontology.loader import Ontology
from agent_readiness.ontology.reasoning.engine import (
    DerivedViolation,
    register,
)
from agent_readiness_insights_protocol.ontology.types import LifecycleState

_RULE_ID = "ontology.inference.irreflexive_dependsOn"


@register(_RULE_ID)
def evaluate(ont: Ontology) -> list[DerivedViolation]:
    out: list[DerivedViolation] = []
    for link in ont.link_instances.get("dependsOn", []):
        if link.lifecycle.state != LifecycleState.RATIFIED:
            continue
        spec = link.spec or {}
        frm = (spec.get("from") or {}).get("id")
        to = (spec.get("to") or {}).get("id")
        if frm and to and frm == to:
            out.append(
                DerivedViolation(
                    rule_id=_RULE_ID,
                    subject_id=link.metadata.get("id"),
                    detail=(
                        f"Reflexive dependsOn link: {frm!r} depends on itself"
                    ),
                    severity="error",
                )
            )
    return out
