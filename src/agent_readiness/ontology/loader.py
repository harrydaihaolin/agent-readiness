"""Read an ontology/ directory; return a typed Ontology value.

Read-only. Returns empty values for missing files/directories.
Rejects malformed YAML via wrapped Pydantic validation errors.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from agent_readiness_insights_protocol.ontology.types import (
    ActionType,
    FunctionType,
    InterfaceType,
    IntentType,
    LinkInstance,
    LinkType,
    ObjectInstance,
    ObjectType,
)


def get_id_template(ot: ObjectType) -> str | None:
    """Return the identity template for an ObjectType.

    Reads ``spec.identity.id_template`` (new) or ``spec.identity.pk_expression``
    (legacy, with deprecation warning). Returns ``None`` when neither is set —
    which the validator treats as "this type opts out of id_template
    enforcement" (see §1.1 of the 2026-05-25 ontology improvement plan).
    """
    spec = ot.spec or {}
    identity = spec.get("identity") or {}
    if "id_template" in identity:
        return str(identity["id_template"])
    if "pk_expression" in identity:
        name = ot.metadata.get("name") if isinstance(ot.metadata, dict) else None
        warnings.warn(
            f"ObjectType {name!r} uses deprecated spec.identity.pk_expression; "
            "rename to id_template.",
            DeprecationWarning,
            stacklevel=2,
        )
        return str(identity["pk_expression"])
    return None


@dataclass
class Ontology:
    object_types: dict[str, ObjectType] = field(default_factory=dict)
    link_types: dict[str, LinkType] = field(default_factory=dict)
    interfaces: dict[str, InterfaceType] = field(default_factory=dict)
    functions: dict[str, FunctionType] = field(default_factory=dict)
    action_types: dict[str, ActionType] = field(default_factory=dict)
    intent_types: dict[str, IntentType] = field(default_factory=dict)
    object_instances: dict[str, list[ObjectInstance]] = field(default_factory=dict)
    link_instances: dict[str, list[LinkInstance]] = field(default_factory=dict)


_TYPE_LOADERS: tuple[tuple[str, type, str], ...] = (
    ("objectTypes", ObjectType, "object_types"),
    ("linkTypes", LinkType, "link_types"),
    ("interfaces", InterfaceType, "interfaces"),
    ("functions", FunctionType, "functions"),
    ("actionTypes", ActionType, "action_types"),
    ("intentTypes", IntentType, "intent_types"),
)


def load_ontology(root: Path) -> Ontology:
    """Load all type definitions and instances under `root`.

    `root` is the path to the `ontology/` directory (not the workspace root).
    Missing directories yield an empty `Ontology`; malformed YAML or schema
    violations raise `ValueError`.
    """
    ont = Ontology()
    if not root.exists():
        return ont

    for subdir, model, attr in _TYPE_LOADERS:
        d = root / subdir
        if not d.is_dir():
            continue
        for yaml_path in sorted(d.glob("*.yaml")):
            raw = yaml.safe_load(yaml_path.read_text())
            if not raw:
                continue
            try:
                instance = model.model_validate(raw)
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid ontology atom at {yaml_path}: {exc}"
                ) from exc
            name = instance.metadata.get("name") if isinstance(instance.metadata, dict) else None
            if not name:
                raise ValueError(
                    f"Ontology atom at {yaml_path} missing metadata.name"
                )
            getattr(ont, attr)[name] = instance

    inst_dir = root / "instances"
    if inst_dir.is_dir():
        for type_dir in sorted(p for p in inst_dir.iterdir() if p.is_dir()):
            type_name = type_dir.name
            for yaml_path in sorted(type_dir.glob("*.yaml")):
                raw = yaml.safe_load(yaml_path.read_text())
                if not raw:
                    continue
                kind = raw.get("kind") if isinstance(raw, dict) else None
                try:
                    if kind == "ObjectInstance":
                        inst: ObjectInstance | LinkInstance = ObjectInstance.model_validate(raw)
                        ont.object_instances.setdefault(type_name, []).append(inst)
                    elif kind == "LinkInstance":
                        inst = LinkInstance.model_validate(raw)
                        ont.link_instances.setdefault(type_name, []).append(inst)
                    else:
                        raise ValueError(
                            f"Unknown instance kind '{kind}' in {yaml_path}"
                        )
                except ValidationError as exc:
                    raise ValueError(
                        f"Invalid ontology instance at {yaml_path}: {exc}"
                    ) from exc

    return ont
