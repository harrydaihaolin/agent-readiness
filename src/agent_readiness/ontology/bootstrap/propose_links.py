"""bootstrap.propose_link_instances — derive typed Links from manifests + scans.

Refuses to run unless the Object Type instances it relies on meet a ratification
threshold (default 80%). Closure invariant — link proposals shouldn't be built on
unreviewed object data.

``releasedAs`` is intentionally deferred in v1: it requires git tag / GitHub API
access and returns an empty envelope with a documented ambiguity until network
access is wired in v2.
"""
from __future__ import annotations

import json
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from agent_readiness_insights_protocol.ontology.bootstrap import (
    Ambiguity,
    Proposal,
    ProposalEnvelope,
)
from agent_readiness_insights_protocol.ontology.types import Lifecycle, LifecycleState

from agent_readiness.ontology.loader import Ontology, load_ontology

_PROPOSED_BY = "bootstrap-mcp"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_pep508_name(spec: str) -> str:
    """Extract the package name from a PEP 508 dep spec ('foo>=1.0', 'foo[extra]', etc)."""
    name = ""
    for ch in spec.strip():
        if ch.isalnum() or ch in ("-", "_", "."):
            name += ch
        else:
            break
    return name


def _ratified_repos(workspace: Path) -> list:
    ont = load_ontology(workspace / "ontology")
    return ont.object_instances.get("Repo", [])


def _check_ratification(repos: list, min_pct: float) -> None:
    if not repos:
        raise RuntimeError(
            "No Repo instances exist. Run bootstrap.propose_object_instances first."
        )
    ratified = sum(1 for r in repos if r.lifecycle.state == LifecycleState.RATIFIED)
    pct = ratified / len(repos)
    if pct < min_pct:
        raise RuntimeError(
            f"Ratification threshold not met: {pct:.0%} < {min_pct:.0%}. "
            f"Ratify Repo instances before proposing links."
        )


def propose_link_instances(
    workspace: Path,
    link_type: str,
    min_ratified_pct: float = 0.8,
) -> ProposalEnvelope:
    repos = _ratified_repos(workspace)
    _check_ratification(repos, min_ratified_pct)
    ont = load_ontology(workspace / "ontology")

    dispatch = {
        "dependsOn": lambda: _propose_depends_on(workspace, repos),
        "providesProtocol": lambda: _propose_provides_protocol(workspace, repos),
        "consumesProtocol": lambda: _propose_consumes_protocol(workspace, repos, ont),
        "vendors": lambda: _propose_vendors(workspace, repos, ont),
        "ownedBy": lambda: _propose_owned_by(workspace, repos),
        "partOf": lambda: _propose_part_of(ont),
        "releasedAs": lambda: _propose_released_as_deferred(),
        "deploysTo": lambda: _propose_deploys_to(workspace, repos),
    }
    if link_type not in dispatch:
        raise NotImplementedError(
            f"link_type={link_type!r} not yet supported. "
            f"v1 supports: {', '.join(sorted(dispatch))}."
        )
    return dispatch[link_type]()


def _propose_depends_on(workspace: Path, repos: Iterable) -> ProposalEnvelope:
    repo_ids = {r.metadata["id"] for r in repos}
    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []
    for repo in repos:
        repo_id = repo.metadata["id"]
        pp = workspace / repo_id / "pyproject.toml"
        if not pp.is_file():
            continue
        try:
            data = tomllib.loads(pp.read_text())
        except tomllib.TOMLDecodeError as exc:
            ambiguities.append(Ambiguity(
                id=f"{repo_id}--?--?",
                reason=f"failed to parse pyproject.toml: {exc}",
            ))
            continue
        deps = (data.get("project") or {}).get("dependencies", [])
        for dep_spec in deps:
            name = _parse_pep508_name(dep_spec)
            if not name:
                continue
            if name == repo_id:
                continue
            if name in repo_ids:
                proposed.append(Proposal(
                    id=f"{repo_id}--dependsOn--{name}",
                    properties={
                        "from": {"object_type": "Repo", "id": repo_id},
                        "to": {"object_type": "Repo", "id": name},
                    },
                    lifecycle=Lifecycle(
                        state=LifecycleState.PROPOSED,
                        proposed_by=_PROPOSED_BY,
                        proposed_at=_now(),
                        confidence=1.0,
                        markers=[],
                    ),
                ))
            else:
                ambiguities.append(Ambiguity(
                    id=f"{repo_id}--?--{name}",
                    reason=f"dep '{name}' in {repo_id} does not match any ratified Repo (likely external)",
                ))

    return ProposalEnvelope(
        tool="bootstrap.propose_link_instances",
        target_type="dependsOn",
        proposed=proposed,
        ambiguities=ambiguities,
    )


def _propose_provides_protocol(workspace: Path, repos: Iterable) -> ProposalEnvelope:
    proposed: list[Proposal] = []
    for repo in repos:
        repo_id = repo.metadata["id"]
        repo_path = workspace / repo_id
        has_schema = (repo_path / "protocol" / "schema.json").is_file()
        name_match = repo_id.endswith("-protocol")
        if not name_match and not has_schema:
            continue
        proposed.append(Proposal(
            id=f"{repo_id}--providesProtocol--{repo_id}",
            properties={
                "from": {"object_type": "Repo", "id": repo_id},
                "to": {"object_type": "Protocol", "id": repo_id},
            },
            lifecycle=Lifecycle(
                state=LifecycleState.PROPOSED,
                proposed_by=_PROPOSED_BY,
                proposed_at=_now(),
                confidence=0.90,
                markers=[],
            ),
        ))

    return ProposalEnvelope(
        tool="bootstrap.propose_link_instances",
        target_type="providesProtocol",
        proposed=proposed,
        ambiguities=[],
    )


def _known_protocol_ids(repos: Iterable, ont: Ontology) -> set[str]:
    ids = {r.metadata["id"] for r in repos if r.metadata["id"].endswith("-protocol")}
    for inst in ont.object_instances.get("Protocol", []):
        ids.add(inst.metadata["id"])
    return ids


def _propose_consumes_protocol(
    workspace: Path,
    repos: Iterable,
    ont: Ontology,
) -> ProposalEnvelope:
    protocol_ids = _known_protocol_ids(repos, ont)
    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []

    for repo in repos:
        repo_id = repo.metadata["id"]
        repo_path = workspace / repo_id
        dep_names: set[str] = set()

        pp = repo_path / "pyproject.toml"
        if pp.is_file():
            try:
                data = tomllib.loads(pp.read_text())
                for dep_spec in (data.get("project") or {}).get("dependencies", []):
                    name = _parse_pep508_name(dep_spec)
                    if name:
                        dep_names.add(name)
            except tomllib.TOMLDecodeError as exc:
                ambiguities.append(Ambiguity(
                    id=f"{repo_id}--?--?",
                    reason=f"failed to parse pyproject.toml: {exc}",
                ))

        pkg = repo_path / "package.json"
        if pkg.is_file():
            try:
                data = json.loads(pkg.read_text())
                for key in ("dependencies", "devDependencies"):
                    for name in (data.get(key) or {}):
                        dep_names.add(name)
            except json.JSONDecodeError as exc:
                ambiguities.append(Ambiguity(
                    id=f"{repo_id}--?--?",
                    reason=f"failed to parse package.json: {exc}",
                ))

        for dep in sorted(dep_names):
            if dep in protocol_ids:
                proposed.append(Proposal(
                    id=f"{repo_id}--consumesProtocol--{dep}",
                    properties={
                        "from": {"object_type": "Repo", "id": repo_id},
                        "to": {"object_type": "Protocol", "id": dep},
                    },
                    lifecycle=Lifecycle(
                        state=LifecycleState.PROPOSED,
                        proposed_by=_PROPOSED_BY,
                        proposed_at=_now(),
                        confidence=0.90,
                        markers=[],
                    ),
                ))

    return ProposalEnvelope(
        tool="bootstrap.propose_link_instances",
        target_type="consumesProtocol",
        proposed=proposed,
        ambiguities=ambiguities,
    )


def _known_rulespack_ids(repos: Iterable, ont: Ontology) -> set[str]:
    ids = {r.metadata["id"] for r in repos if r.metadata["id"].endswith("-rules")}
    for inst in ont.object_instances.get("RulesPack", []):
        ids.add(inst.metadata["id"])
    return ids


def _propose_vendors(
    workspace: Path,
    repos: Iterable,
    ont: Ontology,
) -> ProposalEnvelope:
    rulespack_ids = _known_rulespack_ids(repos, ont)
    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []
    cp_pattern = re.compile(r"cp\s+-r\s+(\S+)/rules\s+\./")
    pip_pattern = re.compile(r"pip\s+install\s+(\S+)")

    for repo in repos:
        repo_id = repo.metadata["id"]
        workflows = workspace / repo_id / ".github" / "workflows"
        if not workflows.is_dir():
            continue
        matched: set[str] = set()
        for wf in workflows.glob("*.yml"):
            text = wf.read_text()
            for pattern in (cp_pattern, pip_pattern):
                for match in pattern.finditer(text):
                    name = match.group(1).strip("'\"")
                    if name in rulespack_ids:
                        matched.add(name)
        for name in sorted(matched):
            proposed.append(Proposal(
                id=f"{repo_id}--vendors--{name}",
                properties={
                    "from": {"object_type": "Repo", "id": repo_id},
                    "to": {"object_type": "RulesPack", "id": name},
                },
                lifecycle=Lifecycle(
                    state=LifecycleState.PROPOSED,
                    proposed_by=_PROPOSED_BY,
                    proposed_at=_now(),
                    confidence=0.85,
                    markers=[],
                ),
            ))

    return ProposalEnvelope(
        tool="bootstrap.propose_link_instances",
        target_type="vendors",
        proposed=proposed,
        ambiguities=ambiguities,
    )


def _parse_codeowners(repo_path: Path) -> tuple[list[str], list[Ambiguity]]:
    """Return owner handles from CODEOWNERS; v1 does not bootstrap Owner instances."""
    ambiguities: list[Ambiguity] = []
    for candidate in (repo_path / "CODEOWNERS", repo_path / ".github" / "CODEOWNERS"):
        if not candidate.is_file():
            continue
        owners: list[str] = []
        wildcard_owners: list[str] = []
        for line in candidate.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            pattern, *handles = parts
            for handle in handles:
                if handle.startswith("@"):
                    if pattern == "*":
                        wildcard_owners.append(handle)
                    owners.append(handle)
        chosen = wildcard_owners or owners
        if not chosen:
            continue
        if len(set(chosen)) > 1:
            ambiguities.append(Ambiguity(
                id=f"{repo_path.name}--?--owners",
                reason="multiple CODEOWNERS entries; using first owner (v1 does not bootstrap Owner instances)",
            ))
        return [chosen[0]], ambiguities
    return [], ambiguities


def _propose_owned_by(workspace: Path, repos: Iterable) -> ProposalEnvelope:
    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []

    for repo in repos:
        repo_id = repo.metadata["id"]
        owners, parse_amb = _parse_codeowners(workspace / repo_id)
        ambiguities.extend(parse_amb)
        if not owners:
            continue
        owner = owners[0]
        confidence = 0.95 if len(parse_amb) == 0 else 0.70
        proposed.append(Proposal(
            id=f"{repo_id}--ownedBy--{owner.lstrip('@')}",
            properties={
                "from": {"object_type": "Repo", "id": repo_id},
                # v1 does not bootstrap Owner Object Type instances
                "to": {"object_type": "Owner", "id": owner},
            },
            lifecycle=Lifecycle(
                state=LifecycleState.PROPOSED,
                proposed_by=_PROPOSED_BY,
                proposed_at=_now(),
                confidence=confidence,
                markers=[],
            ),
        ))

    return ProposalEnvelope(
        tool="bootstrap.propose_link_instances",
        target_type="ownedBy",
        proposed=proposed,
        ambiguities=ambiguities,
    )


def _propose_part_of(ont: Ontology) -> ProposalEnvelope:
    modules = ont.object_instances.get("Module", [])
    if not modules:
        return ProposalEnvelope(
            tool="bootstrap.propose_link_instances",
            target_type="partOf",
            proposed=[],
            ambiguities=[
                Ambiguity(
                    id="partOf--no-modules",
                    reason="Module instances not yet bootstrapped — partOf requires them",
                )
            ],
        )
    return ProposalEnvelope(
        tool="bootstrap.propose_link_instances",
        target_type="partOf",
        proposed=[],
        ambiguities=[],
    )


def _propose_released_as_deferred() -> ProposalEnvelope:
    return ProposalEnvelope(
        tool="bootstrap.propose_link_instances",
        target_type="releasedAs",
        proposed=[],
        ambiguities=[
            Ambiguity(
                id="releasedAs--deferred",
                reason="v1 requires git tag / gh API; deferred to v2 when network access is wired",
            )
        ],
    )


def _propose_deploys_to(workspace: Path, repos: Iterable) -> ProposalEnvelope:
    """Best-effort deploysTo from workflow environment declarations.

    v1 does not bootstrap Service or Environment Object Type instances; links
    reference those types by convention using the repo id as the Service id.
    """
    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []
    env_pattern = re.compile(r"^\s*environment:\s*(\S+)\s*$", re.MULTILINE)

    for repo in repos:
        repo_id = repo.metadata["id"]
        workflows = workspace / repo_id / ".github" / "workflows"
        if not workflows.is_dir():
            continue
        envs: set[str] = set()
        for wf in sorted(workflows.glob("deploy*.yml")):
            for match in env_pattern.finditer(wf.read_text()):
                envs.add(match.group(1).strip("'\""))
        for env_name in sorted(envs):
            proposed.append(Proposal(
                id=f"{repo_id}--deploysTo--{env_name}",
                properties={
                    "from": {"object_type": "Service", "id": repo_id},
                    "to": {"object_type": "Environment", "id": env_name},
                },
                lifecycle=Lifecycle(
                    state=LifecycleState.PROPOSED,
                    proposed_by=_PROPOSED_BY,
                    proposed_at=_now(),
                    confidence=0.70,
                    markers=[],
                ),
            ))

    if proposed:
        ambiguities.append(Ambiguity(
            id="deploysTo--no-service-env-instances",
            reason="v1 does not bootstrap Service or Environment instances; links are best-effort",
        ))

    return ProposalEnvelope(
        tool="bootstrap.propose_link_instances",
        target_type="deploysTo",
        proposed=proposed,
        ambiguities=ambiguities,
    )
