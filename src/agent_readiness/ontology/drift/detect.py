"""Compute drift between ratified ontology and observed workspace reality.

Algorithm:
  1. Load ratified Object instances from ontology/instances/.
  2. Re-run propose_object_instances against the live filesystem.
  3. Diff: each ratified atom either has a matching live atom (clean),
     a renamed candidate (heuristic match on properties), or no match (REMOVED).
     Each live atom not matched to a ratified one is ADDED.
  4. For matched atoms, compare properties → CHANGED if differ.
"""
from __future__ import annotations

from pathlib import Path

from agent_readiness_insights_protocol.ontology.drift import DriftDelta, DriftKind, DriftReport

from agent_readiness.ontology.bootstrap.propose_objects import propose_object_instances
from agent_readiness.ontology.loader import load_ontology

_RENAME_PROPERTY_MATCH_THRESHOLD = 0.7  # share ≥70% of properties to be a rename candidate


def detect_drift(workspace: Path) -> DriftReport:
    ont = load_ontology(workspace / "ontology")
    ratified_repos = {
        r.metadata["id"]: r
        for r in ont.object_instances.get("Repo", [])
        if r.lifecycle.state.value == "ratified"
    }

    live_env = propose_object_instances(workspace, object_type="Repo")
    live_props_by_id = {p.id: p.properties for p in live_env.proposed}

    deltas: list[DriftDelta] = []
    matched_live: set[str] = set()

    for ratified_id, ratified_inst in ratified_repos.items():
        ratified_props = ratified_inst.spec["properties"]
        # Direct match?
        if ratified_id in live_props_by_id:
            live = live_props_by_id[ratified_id]
            changed_keys = [k for k in ratified_props if ratified_props.get(k) != live.get(k)]
            if changed_keys:
                interface_claimed = bool(ratified_inst.spec.get("implements"))
                deltas.append(DriftDelta(
                    kind=DriftKind.CHANGED,
                    atom_id=ratified_id,
                    atom_type="Repo",
                    changed_properties=changed_keys,
                    interface_claimed=interface_claimed,
                ))
            matched_live.add(ratified_id)
            continue
        # Rename candidate?
        rename = _find_rename_candidate(ratified_props, live_props_by_id, matched_live)
        if rename:
            deltas.append(DriftDelta(
                kind=DriftKind.RENAMED,
                atom_id=ratified_id,
                atom_type="Repo",
                new_id=rename,
            ))
            matched_live.add(rename)
            continue
        # No match → REMOVED
        deltas.append(DriftDelta(
            kind=DriftKind.REMOVED,
            atom_id=ratified_id,
            atom_type="Repo",
            interface_claimed=bool(ratified_inst.spec.get("implements")),
        ))

    for live_id in live_props_by_id:
        if live_id not in matched_live:
            deltas.append(DriftDelta(kind=DriftKind.ADDED, atom_id=live_id, atom_type="Repo"))

    return DriftReport(deltas=deltas)


def _find_rename_candidate(ratified_props, live_props_by_id, already_matched) -> str | None:
    best_match_id = None
    best_overlap = 0.0
    for live_id, live in live_props_by_id.items():
        if live_id in already_matched:
            continue
        keys = set(ratified_props) | set(live)
        if not keys:
            continue
        overlap = sum(1 for k in keys if ratified_props.get(k) == live.get(k)) / len(keys)
        if overlap > best_overlap and overlap >= _RENAME_PROPERTY_MATCH_THRESHOLD:
            best_overlap = overlap
            best_match_id = live_id
    return best_match_id
