"""status — per-type counts of proposed vs ratified atoms."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_readiness_insights_protocol.ontology.types import LifecycleState

from agent_readiness.ontology.loader import load_ontology


@dataclass
class TypeStatus:
    declared: int = 0
    proposed_instances: int = 0
    ratified_instances: int = 0


@dataclass
class StatusReport:
    object_types: dict[str, TypeStatus] = field(default_factory=dict)
    link_types: dict[str, TypeStatus] = field(default_factory=dict)
    interfaces_declared: int = 0
    functions_declared: int = 0
    action_types_declared: int = 0
    intent_types_declared: int = 0


def status_ontology(root: Path) -> StatusReport:
    ont = load_ontology(root)
    rep = StatusReport(
        interfaces_declared=len(ont.interfaces),
        functions_declared=len(ont.functions),
        action_types_declared=len(ont.action_types),
        intent_types_declared=len(ont.intent_types),
    )
    for type_name in ont.object_types:
        ts = TypeStatus(declared=1)
        for inst in ont.object_instances.get(type_name, []):
            if inst.lifecycle.state == LifecycleState.RATIFIED:
                ts.ratified_instances += 1
            else:
                ts.proposed_instances += 1
        rep.object_types[type_name] = ts
    for type_name in ont.link_types:
        ts = TypeStatus(declared=1)
        for link in ont.link_instances.get(type_name, []):
            if link.lifecycle.state == LifecycleState.RATIFIED:
                ts.ratified_instances += 1
            else:
                ts.proposed_instances += 1
        rep.link_types[type_name] = ts
    return rep
