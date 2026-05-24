"""bootstrap.propose_interface_claims — evaluate Interface satisfaction proofs against ratified Repos.

For each ratified Repo × declared Interface, evaluate the Interface's
`satisfaction_proof:` block as a small declarative predicate. Emit one
InterfaceClaim per (Repo, Interface) pair:
- `satisfaction: ratified` if all clauses pass; `proof_refs` lists matched paths.
- `satisfaction: failing` otherwise.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from agent_readiness_insights_protocol.ontology.bootstrap import (
    Proposal,
    ProposalEnvelope,
)
from agent_readiness_insights_protocol.ontology.types import Lifecycle, LifecycleState

from agent_readiness.ontology.loader import load_ontology


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_exists(clause: dict, repo_root: Path) -> tuple[bool, list[str]]:
    path = clause.get("path")
    if not path:
        return False, []
    full = repo_root / path
    return full.exists(), [path] if full.exists() else []


def _file_glob(clause: dict, repo_root: Path) -> tuple[bool, list[str]]:
    paths = clause.get("paths") or ([clause["path"]] if clause.get("path") else [])
    matched: list[str] = []
    for pat in paths:
        for p in repo_root.glob(pat):
            if p.exists():
                matched.append(str(p.relative_to(repo_root)))
    return bool(matched), matched


def _substitute_templates(value: str, context: dict) -> str:
    for key, val in context.items():
        value = value.replace(f"{{{{ {key} }}}}", str(val))
        value = value.replace(f"{{{{{key}}}}}", str(val))
    return value


def _regex_match(clause: dict, repo_root: Path, context: dict | None = None) -> tuple[bool, list[str]]:
    file_field = clause.get("file") or clause.get("path")
    pattern = clause.get("pattern")
    if not file_field or not pattern:
        return False, []
    if context and "{{" in file_field:
        file_field = _substitute_templates(file_field, context)
    # Handle template placeholders like "{{ primary_manifest }}" — best-effort,
    # leave unsubstituted if no context. Skip on missing file.
    if "{{" in file_field:
        # Could not substitute; treat as not-matched but no error.
        return False, []
    target = repo_root / file_field
    if not target.is_file():
        return False, []
    try:
        text = target.read_text()
    except (OSError, UnicodeDecodeError):
        return False, []
    if re.search(pattern, text):
        return True, [file_field]
    return False, []


def _command_clause(clause: dict, repo_root: Path) -> tuple[bool, list[str]]:
    # Bootstrap does NOT execute commands; treat command clauses as "pending".
    # Returns False with no proof refs so the claim is `failing` until manually verified.
    return False, []


_LEAF_DISPATCH = {
    "file_exists": _file_exists,
    "file_glob": _file_glob,
    "regex_match": _regex_match,
    "command": _command_clause,
}


def _evaluate_proof(
    proof: dict, repo_root: Path, context: dict | None = None,
) -> tuple[bool, list[str]]:
    t = proof.get("type")
    if t == "composite":
        op = proof.get("op", "and")
        clauses = proof.get("clauses", [])
        results = [_evaluate_proof(c, repo_root, context) for c in clauses]
        passed_all = all(r[0] for r in results)
        passed_any = any(r[0] for r in results)
        proofs = [p for r in results for p in r[1]]
        if op == "and":
            return passed_all, proofs if passed_all else []
        elif op == "or":
            return passed_any, proofs if passed_any else []
        else:
            return False, []
    handler = _LEAF_DISPATCH.get(t)
    if handler:
        if t == "regex_match":
            return handler(proof, repo_root, context)
        return handler(proof, repo_root)
    return False, []


def propose_interface_claims(workspace: Path, interface: str) -> ProposalEnvelope:
    """Evaluate `interface` against every ratified Repo in workspace's ontology."""
    ont = load_ontology(workspace / "ontology")
    if interface not in ont.interfaces:
        raise ValueError(f"Interface {interface!r} not declared in ontology/interfaces/")
    iface = ont.interfaces[interface]
    proof_block = iface.spec.get("satisfaction_proof")
    if not isinstance(proof_block, dict):
        raise ValueError(f"Interface {interface!r} missing satisfaction_proof block")

    repos = ont.object_instances.get("Repo", [])
    ratified_repos = [r for r in repos if r.lifecycle.state == LifecycleState.RATIFIED]

    proposed: list[Proposal] = []
    for repo in ratified_repos:
        repo_id = repo.metadata["id"]
        repo_root = workspace / repo_id
        context = repo.spec.get("properties", {})
        passed, proof_refs = _evaluate_proof(proof_block, repo_root, context)
        satisfaction = "ratified" if passed else "failing"
        confidence = 0.95 if passed else 0.70
        proposed.append(Proposal(
            id=f"{repo_id}--implements--{interface}",
            properties={
                "object_id": repo_id,
                "interface": interface,
                "satisfaction": satisfaction,
                "proof_refs": proof_refs,
            },
            lifecycle=Lifecycle(
                state=LifecycleState.PROPOSED,
                proposed_by="bootstrap-mcp",
                proposed_at=_now(),
                confidence=confidence,
                markers=[],
            ),
        ))

    return ProposalEnvelope(
        tool="bootstrap.propose_interface_claims",
        target_type=interface,
        proposed=proposed,
    )
