"""validate — load + structural check; with --strict, enforces closure invariant."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_readiness_insights_protocol.ontology.types import LifecycleState

from agent_readiness.ontology.loader import load_ontology


@dataclass
class ValidationIssue:
    kind: str
    atom_id: str
    message: str


@dataclass
class ValidationReport:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)


def validate_ontology(root: Path, strict: bool = False) -> ValidationReport:
    """Load the ontology; if `strict`, enforce: ratified atoms may not reference
    unratified atoms via dependsOn-style links."""
    ont = load_ontology(root)
    issues: list[ValidationIssue] = []

    if strict:
        # Build set of ratified ObjectInstance ids
        ratified_obj_ids: set[str] = set()
        for type_name, insts in ont.object_instances.items():
            for inst in insts:
                if inst.lifecycle.state == LifecycleState.RATIFIED:
                    atom_id = inst.metadata.get("id", "<unknown>")
                    ratified_obj_ids.add(atom_id)

        # Walk ratified LinkInstances; if either endpoint id is not ratified, flag
        for type_name, insts in ont.link_instances.items():
            for link in insts:
                if link.lifecycle.state != LifecycleState.RATIFIED:
                    continue
                link_id = link.metadata.get("id", "<unknown>")
                spec = link.spec or {}
                for end in ("from", "to"):
                    endpoint = spec.get(end) or {}
                    target_id = endpoint.get("id")
                    if target_id and target_id not in ratified_obj_ids:
                        issues.append(ValidationIssue(
                            kind="closure_violation",
                            atom_id=link_id,
                            message=(
                                f"ratified link {link_id} references unratified "
                                f"{endpoint.get('object_type', '?')} '{target_id}' ({end})"
                            ),
                        ))

    return ValidationReport(ok=not issues, issues=issues)
