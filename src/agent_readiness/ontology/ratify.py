"""ratify — bump a proposed atom to ratified state, in place."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_readiness_insights_protocol.ontology.types import (
    LinkInstance,
    ObjectInstance,
)


def _find_atom_file(workspace: Path, atom_id: str) -> tuple[Path, dict]:
    """Walk workspace/ontology/instances/**/*.yaml looking for metadata.id == atom_id."""
    inst_root = workspace / "ontology" / "instances"
    if not inst_root.is_dir():
        raise FileNotFoundError(f"No instances dir under {workspace}")
    for yaml_path in inst_root.rglob("*.yaml"):
        try:
            raw = yaml.safe_load(yaml_path.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(raw, dict):
            continue
        meta = raw.get("metadata") or {}
        if meta.get("id") == atom_id:
            return yaml_path, raw
    raise LookupError(f"Atom not found: {atom_id}")


def ratify_atom(workspace: Path, atom_id: str, ratified_by: str) -> Path:
    """Bump the atom's lifecycle.state to 'ratified'. Refuses if markers non-empty.

    Returns the path to the modified file.
    """
    path, raw = _find_atom_file(workspace, atom_id)
    lc = raw.get("lifecycle") or {}
    markers = lc.get("markers") or []
    if markers:
        raise ValueError(
            f"Refusing to ratify {atom_id}: unresolved markers {markers}. "
            "Resolve them by editing the YAML, then re-run."
        )
    if lc.get("state") == "ratified":
        # Idempotent: already ratified, no-op
        return path
    lc["state"] = "ratified"
    lc["ratified_by"] = ratified_by
    lc["ratified_at"] = datetime.now(timezone.utc).isoformat()
    raw["lifecycle"] = lc

    # Validate via Pydantic before writing back
    kind = raw.get("kind")
    if kind == "ObjectInstance":
        ObjectInstance.model_validate(raw)
    elif kind == "LinkInstance":
        LinkInstance.model_validate(raw)
    else:
        raise ValueError(f"Unknown atom kind {kind!r} in {path}")

    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return path
