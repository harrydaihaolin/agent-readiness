"""bootstrap.propose_object_instances — propose Object Type instances from observed signals.

Deterministic core (filesystem walk + manifest detection). No LLM in v1;
LLM augmentation (e.g. naming-pattern grouping into Systems) is gated and lives
in a sibling module not shipped with M1.3.

v1 supports Repo, Library, Protocol, and RulesPack.
"""
from __future__ import annotations

import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import yaml

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


def _git_subdirs(workspace: Path) -> list[Path]:
    return sorted(p for p in workspace.iterdir() if p.is_dir() and (p / ".git").exists())


def propose_object_instances(
    workspace: Path,
    object_type: str,
) -> ProposalEnvelope:
    """Propose Object Type instances for `object_type` under `workspace`."""
    dispatch = {
        "Repo": _propose_repos,
        "Library": _propose_libraries,
        "Protocol": _propose_protocols,
        "RulesPack": _propose_rulespacks,
    }
    if object_type not in dispatch:
        raise NotImplementedError(
            f"propose_object_instances for object_type={object_type!r} "
            "not yet supported. v1 supports: Repo, Library, Protocol, RulesPack."
        )
    return dispatch[object_type](workspace)


def _propose_repos(workspace: Path) -> ProposalEnvelope:
    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []

    for child in _git_subdirs(workspace):
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


def _propose_libraries(workspace: Path) -> ProposalEnvelope:
    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []

    for child in _git_subdirs(workspace):
        repo_id = child.name
        source_repo = {"object_type": "Repo", "id": repo_id}

        pp = child / "pyproject.toml"
        if pp.is_file():
            try:
                data = tomllib.loads(pp.read_text())
            except tomllib.TOMLDecodeError as exc:
                ambiguities.append(
                    Ambiguity(id=repo_id, reason=f"failed to parse pyproject.toml: {exc}")
                )
            else:
                project = data.get("project") or {}
                name = project.get("name")
                version = project.get("version")
                if name:
                    markers: list[str] = []
                    if not version:
                        markers.append("spec.properties.version")
                    proposed.append(
                        Proposal(
                            id=f"pypi#{name}",
                            properties={
                                "name": str(name),
                                "version": version or "???",
                                "registry": "pypi",
                                "source_repo": source_repo,
                            },
                            lifecycle=Lifecycle(
                                state=LifecycleState.PROPOSED,
                                proposed_by=_PROPOSED_BY,
                                proposed_at=_now(),
                                confidence=0.95 if version else 0.50,
                                markers=markers,
                            ),
                        )
                    )

        pkg = child / "package.json"
        if pkg.is_file():
            try:
                data = json.loads(pkg.read_text())
            except json.JSONDecodeError as exc:
                ambiguities.append(
                    Ambiguity(id=repo_id, reason=f"failed to parse package.json: {exc}")
                )
            else:
                name = data.get("name")
                version = data.get("version")
                if name:
                    markers = []
                    if not version:
                        markers.append("spec.properties.version")
                    proposed.append(
                        Proposal(
                            id=f"npm#{name}",
                            properties={
                                "name": str(name),
                                "version": version or "???",
                                "registry": "npm",
                                "source_repo": source_repo,
                            },
                            lifecycle=Lifecycle(
                                state=LifecycleState.PROPOSED,
                                proposed_by=_PROPOSED_BY,
                                proposed_at=_now(),
                                confidence=0.95 if version else 0.50,
                                markers=markers,
                            ),
                        )
                    )

    return ProposalEnvelope(
        tool="bootstrap.propose_object_instances",
        target_type="Library",
        proposed=proposed,
        ambiguities=ambiguities,
    )


def _propose_protocols(workspace: Path) -> ProposalEnvelope:
    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []

    for child in _git_subdirs(workspace):
        repo_id = child.name
        schema_path = child / "protocol" / "schema.json"
        has_schema = schema_path.is_file()
        name_match = repo_id.endswith("-protocol")

        if not name_match and not has_schema:
            continue

        version: str | None = None
        pp = child / "pyproject.toml"
        if pp.is_file():
            try:
                data = tomllib.loads(pp.read_text())
                version = (data.get("project") or {}).get("version")
            except tomllib.TOMLDecodeError as exc:
                ambiguities.append(
                    Ambiguity(id=repo_id, reason=f"failed to parse pyproject.toml: {exc}")
                )

        markers: list[str] = []
        properties: dict[str, object] = {"name": repo_id}
        if has_schema:
            properties["schema_path"] = "protocol/schema.json"
        if version:
            properties["version"] = version
        else:
            properties["version"] = "???"
            markers.append("spec.properties.version")

        if name_match:
            confidence = 0.90 if version else 0.50
        else:
            confidence = 0.85 if version else 0.50

        proposed.append(
            Proposal(
                id=f"{repo_id}@{version or '???'}",
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
        target_type="Protocol",
        proposed=proposed,
        ambiguities=ambiguities,
    )


def _is_rulespack(child: Path) -> bool:
    rules_dir = child / "rules"
    if not rules_dir.is_dir():
        return False
    for yaml_path in rules_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(yaml_path.read_text())
        except Exception:
            continue
        if isinstance(data, dict) and "rules_version" in data:
            return True
    return False


def _read_version_from_manifests(child: Path) -> tuple[str | None, list[Ambiguity]]:
    ambiguities: list[Ambiguity] = []
    repo_id = child.name

    pp = child / "pyproject.toml"
    if pp.is_file():
        try:
            data = tomllib.loads(pp.read_text())
            version = (data.get("project") or {}).get("version")
            if version:
                return str(version), ambiguities
        except tomllib.TOMLDecodeError as exc:
            ambiguities.append(
                Ambiguity(id=repo_id, reason=f"failed to parse pyproject.toml: {exc}")
            )

    pkg = child / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text())
            version = data.get("version")
            if version:
                return str(version), ambiguities
        except json.JSONDecodeError as exc:
            ambiguities.append(
                Ambiguity(id=repo_id, reason=f"failed to parse package.json: {exc}")
            )

    return None, ambiguities


def _propose_rulespacks(workspace: Path) -> ProposalEnvelope:
    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []

    for child in _git_subdirs(workspace):
        if not _is_rulespack(child):
            continue

        repo_id = child.name
        version, version_amb = _read_version_from_manifests(child)
        ambiguities.extend(version_amb)

        markers: list[str] = []
        properties: dict[str, object] = {"name": repo_id}
        if version:
            properties["version"] = version
            confidence = 0.90
        else:
            properties["version"] = "???"
            markers.append("spec.properties.version")
            confidence = 0.60

        proposed.append(
            Proposal(
                id=f"{repo_id}@{version or '???'}",
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
        target_type="RulesPack",
        proposed=proposed,
        ambiguities=ambiguities,
    )
