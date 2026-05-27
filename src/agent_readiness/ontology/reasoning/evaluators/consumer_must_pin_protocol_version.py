"""Inference: every ``consumesProtocol`` target must carry a version pin.

The manifest convention is that a ratified ``consumesProtocol`` link
targets a *versioned* Protocol id of the form ``<name>@<X.Y.Z>``
(e.g. ``agent-readiness-insights-protocol@0.10.0``). Pointing at the
unversioned name is a smell — the consumer is implicitly tracking
``latest``, which silently breaks under upstream majors. Catching
this here as a derived fact (rather than per-file) means the rule
fires across the umbrella regardless of which sub-repo's pyproject
introduced the slip.
"""

from __future__ import annotations

from agent_readiness.ontology.loader import Ontology
from agent_readiness.ontology.reasoning.engine import (
    DerivedViolation,
    register,
)
from agent_readiness_insights_protocol.ontology.types import LifecycleState

_RULE_ID = "ontology.inference.consumer_must_pin_protocol_version"


@register(_RULE_ID)
def evaluate(ont: Ontology) -> list[DerivedViolation]:
    out: list[DerivedViolation] = []
    for link in ont.link_instances.get("consumesProtocol", []):
        if link.lifecycle.state != LifecycleState.RATIFIED:
            continue
        spec = link.spec or {}
        to_ref = spec.get("to") or {}
        target_id = to_ref.get("id")
        if not target_id:
            continue
        if "@" in target_id:
            continue
        from_ref = spec.get("from") or {}
        from_id = from_ref.get("id") or "<unknown>"
        out.append(
            DerivedViolation(
                rule_id=_RULE_ID,
                subject_id=link.metadata.get("id"),
                detail=(
                    f"consumesProtocol from {from_id!r} targets "
                    f"unversioned protocol id {target_id!r} — "
                    "every consumesProtocol target must carry an "
                    "@X.Y.Z pin so consumers cannot silently track latest"
                ),
                severity="warn",
            )
        )
    return out
