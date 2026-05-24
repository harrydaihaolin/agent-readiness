"""M4.1 — read-only ontology data tools."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_readiness.ontology.loader import load_ontology
from agent_readiness_insights_protocol.ontology.types import Lifecycle, LifecycleState


def _lifecycle_dict(lifecycle: Lifecycle) -> dict[str, Any]:
    return {
        "state": lifecycle.state.value,
        "ratified_by": lifecycle.ratified_by,
        "ratified_at": lifecycle.ratified_at,
    }


def _object_instance_dict(inst: Any, object_type: str) -> dict[str, Any]:
    spec = inst.spec or {}
    return {
        "id": inst.metadata.get("id"),
        "type": object_type,
        "properties": spec.get("properties", {}),
        "implements": spec.get("implements", []),
        "lifecycle": _lifecycle_dict(inst.lifecycle),
    }


def list_object_types(workspace: Path) -> list[dict[str, Any]]:
    """Return one dict per ratified ObjectType declaration."""
    ont = load_ontology(workspace / "ontology")
    out: list[dict[str, Any]] = []
    for name, obj_type in ont.object_types.items():
        metadata = obj_type.metadata or {}
        spec = obj_type.spec or {}
        out.append(
            {
                "name": name,
                "description": metadata.get("description"),
                "properties_schema": spec.get("properties", []),
            }
        )
    return out


def query_objects(
    workspace: Path,
    object_type: str,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return ratified ObjectInstances of ``object_type``, optionally filtered."""
    ont = load_ontology(workspace / "ontology")
    instances = ont.object_instances.get(object_type, [])
    out: list[dict[str, Any]] = []
    for inst in instances:
        if inst.lifecycle.state != LifecycleState.RATIFIED:
            continue
        props = (inst.spec or {}).get("properties", {})
        if where and any(props.get(k) != v for k, v in where.items()):
            continue
        out.append(_object_instance_dict(inst, object_type))
    return out


def list_links(
    workspace: Path,
    from_id: str | None = None,
    to_id: str | None = None,
    link_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return ratified LinkInstances filtered by from/to/type."""
    ont = load_ontology(workspace / "ontology")
    out: list[dict[str, Any]] = []
    for type_name, instances in ont.link_instances.items():
        if link_type is not None and type_name != link_type:
            continue
        for inst in instances:
            if inst.lifecycle.state != LifecycleState.RATIFIED:
                continue
            spec = inst.spec or {}
            from_ref = spec.get("from") or {}
            to_ref = spec.get("to") or {}
            if from_id is not None and from_ref.get("id") != from_id:
                continue
            if to_id is not None and to_ref.get("id") != to_id:
                continue
            out.append(
                {
                    "id": inst.metadata.get("id"),
                    "type": type_name,
                    "from": from_ref,
                    "to": to_ref,
                    "properties": spec.get("properties", {}),
                    "lifecycle": _lifecycle_dict(inst.lifecycle),
                }
            )
    return out


def get_object(workspace: Path, object_id: str) -> dict[str, Any] | None:
    """Return the ObjectInstance with ``metadata.id == object_id``, or ``None``."""
    ont = load_ontology(workspace / "ontology")
    for object_type, instances in ont.object_instances.items():
        for inst in instances:
            if inst.metadata.get("id") != object_id:
                continue
            if inst.lifecycle.state != LifecycleState.RATIFIED:
                return None
            return _object_instance_dict(inst, object_type)
    return None


def list_interfaces(workspace: Path) -> list[dict[str, Any]]:
    """Return one dict per declared InterfaceType."""
    ont = load_ontology(workspace / "ontology")
    out: list[dict[str, Any]] = []
    for name, iface in ont.interfaces.items():
        metadata = iface.metadata or {}
        spec = iface.spec or {}
        out.append(
            {
                "name": name,
                "description": metadata.get("description"),
                "satisfaction_proof": spec.get("satisfaction_proof"),
            }
        )
    return out


def which_interfaces(workspace: Path, object_id: str) -> list[dict[str, Any]]:
    """Return interface claims for the given Object's ``spec.implements`` list."""
    obj = get_object(workspace, object_id)
    if obj is None:
        return []
    implements = obj.get("implements") or []
    out: list[dict[str, Any]] = []
    for claim in implements:
        if not isinstance(claim, dict):
            continue
        out.append(
            {
                "interface": claim.get("interface"),
                "satisfaction": claim.get("satisfaction"),
                "last_checked": claim.get("last_checked"),
                "proof_refs": claim.get("proof_refs", []),
            }
        )
    return out
