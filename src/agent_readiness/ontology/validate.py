"""validate — load + structural check; with --strict, enforces closure invariant.

Always-on checks (regardless of ``strict``):

- **Check A (§1.1):** every ``ObjectInstance.metadata.id`` must equal
  ``compute_pk(object_type.id_template, properties)``.
- **Check B (§1.2):** every ``LinkInstance.spec.{from,to}.id`` must
  resolve to an existing ``ObjectInstance`` file. Lifecycle-independent
  — a proposed link with a missing endpoint is still broken.

Strict-only:

- **Closure invariant:** ratified atoms may not reference unratified
  atoms via dependsOn-style links.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_readiness_insights_protocol.ontology.types import LifecycleState

from agent_readiness.ontology.identity import compute_pk
from agent_readiness.ontology.loader import get_id_template, load_ontology


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
    """Load the ontology; run always-on Checks A and B; under ``strict`` also
    enforce the ratified-atoms-may-not-reference-unratified closure invariant.
    """
    ont = load_ontology(root)
    issues: list[ValidationIssue] = []

    # Check A: instance metadata.id matches compute_pk(object_type.id_template, properties)
    for type_name, insts in ont.object_instances.items():
        ot = ont.object_types.get(type_name)
        if ot is None:
            continue
        template = get_id_template(ot)
        if template is None:
            continue
        for inst in insts:
            atom_id = inst.metadata.get("id", "<unknown>") if isinstance(inst.metadata, dict) else "<unknown>"
            properties = (inst.spec or {}).get("properties") or {}
            try:
                expected = compute_pk(template, properties)
            except KeyError as exc:
                issues.append(ValidationIssue(
                    kind="id_template_unresolved",
                    atom_id=str(atom_id),
                    message=(
                        f"{type_name} instance {atom_id!r} cannot render "
                        f"id_template {template!r}: missing property "
                        f"{exc.args[0]!r}"
                    ),
                ))
                continue
            if atom_id != expected:
                issues.append(ValidationIssue(
                    kind="id_template_mismatch",
                    atom_id=str(atom_id),
                    message=(
                        f"{type_name} instance metadata.id={atom_id!r} does "
                        f"not match rendered id_template {template!r} "
                        f"(expected {expected!r}, from properties "
                        f"name={properties.get('name')!r})"
                    ),
                ))

    # Check B: link endpoints (from/to) must resolve to an existing ObjectInstance.
    object_index: set[tuple[str, str]] = set()
    for type_name, insts in ont.object_instances.items():
        for inst in insts:
            atom_id = inst.metadata.get("id") if isinstance(inst.metadata, dict) else None
            if atom_id is not None:
                object_index.add((type_name, str(atom_id)))

    for type_name, links in ont.link_instances.items():
        for link in links:
            link_id = link.metadata.get("id", "<unknown>") if isinstance(link.metadata, dict) else "<unknown>"
            spec = link.spec or {}
            for end in ("from", "to"):
                endpoint = spec.get(end) or {}
                target_type = endpoint.get("object_type")
                target_id = endpoint.get("id")
                if not target_type or not target_id:
                    continue
                if (target_type, str(target_id)) not in object_index:
                    issues.append(ValidationIssue(
                        kind="link_target_missing",
                        atom_id=str(link_id),
                        message=(
                            f"link {link_id} {end} references {target_type} "
                            f"{target_id!r} which has no instance file under "
                            f"ontology/instances/{target_type}/"
                        ),
                    ))

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
