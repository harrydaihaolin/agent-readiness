"""bootstrap.propose_object_instances — propose Object Type instances from observed signals.

Deterministic core (filesystem walk + manifest detection). No LLM in v1;
LLM augmentation (e.g. naming-pattern grouping into Systems) is gated and lives
in a sibling module not shipped with M1.3.

v1 supports `object_type="Repo"` only; Library/Protocol/RulesPack land in M1.4.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agent_readiness_insights_protocol.ontology.bootstrap import (
    Ambiguity,
    Proposal,
    ProposalEnvelope,
)
from agent_readiness_insights_protocol.ontology.types import Lifecycle, LifecycleState

_PROPOSED_BY = "bootstrap-mcp"

# Ordered by precedence when multiple manifests are present (none — we mark as ambiguous instead).
_MANIFEST_LANGUAGE: dict[str, list[str]] = {
    "pyproject.toml": ["python"],
    "setup.py": ["python"],
    "package.json": ["typescript"],
    "go.mod": ["go"],
    "Cargo.toml": ["rust"],
    "build.gradle": ["jvm"],
    "build.gradle.kts": ["jvm"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def propose_object_instances(
    workspace: Path,
    object_type: str,
) -> ProposalEnvelope:
    """Propose Object Type instances for `object_type` under `workspace`.

    Currently supports `object_type="Repo"`. Other Object Types raise
    NotImplementedError until M1.4 lands them.
    """
    if object_type != "Repo":
        raise NotImplementedError(
            f"propose_object_instances for object_type={object_type!r} "
            "ships in M1.4 (Library/Protocol/RulesPack)."
        )

    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []

    for child in sorted(p for p in workspace.iterdir() if p.is_dir()):
        if not (child / ".git").exists():
            continue
        manifests = [m for m in _MANIFEST_LANGUAGE if (child / m).is_file()]
        markers: list[str] = []
        properties: dict[str, object] = {"name": child.name}

        if not manifests:
            properties["primary_manifest"] = "???"
            properties["languages"] = ["???"]
            markers.extend([
                "spec.properties.primary_manifest",
                "spec.properties.languages",
            ])
            ambiguities.append(
                Ambiguity(id=child.name, reason="no recognized manifest present")
            )
            confidence = 0.20
        elif len(manifests) == 1:
            properties["primary_manifest"] = manifests[0]
            properties["languages"] = list(_MANIFEST_LANGUAGE[manifests[0]])
            confidence = 0.95
        else:
            properties["primary_manifest"] = "???"
            properties["languages"] = ["???"]
            markers.extend([
                "spec.properties.primary_manifest",
                "spec.properties.languages",
            ])
            ambiguities.append(
                Ambiguity(
                    id=child.name,
                    reason=f"multiple manifests present: {manifests}",
                )
            )
            confidence = 0.40

        proposed.append(
            Proposal(
                id=child.name,
                properties=properties,
                lifecycle=Lifecycle(
                    state=LifecycleState.PROPOSED,
                    proposed_by=_PROPOSED_BY,
                    proposed_at=_now(),
                    confidence=confidence,
                    markers=markers,
                ),
            )
        )

    return ProposalEnvelope(
        tool="bootstrap.propose_object_instances",
        target_type="Repo",
        proposed=proposed,
        ambiguities=ambiguities,
    )
