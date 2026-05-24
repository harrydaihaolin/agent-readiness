"""bootstrap.propose_link_instances — derive typed Links from manifests + scans.

Refuses to run unless the Object Type instances it relies on meet a ratification
threshold (default 80%). Closure invariant — link proposals shouldn't be built on
unreviewed object data.
"""
from __future__ import annotations

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

from agent_readiness.ontology.loader import load_ontology

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
    if link_type == "dependsOn":
        return _propose_depends_on(workspace, repos)
    raise NotImplementedError(
        f"link_type={link_type!r} not yet supported in M1.5. M1.6 adds others."
    )


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
