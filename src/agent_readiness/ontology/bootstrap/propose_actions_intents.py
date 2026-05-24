"""bootstrap.propose_action_intent_types — detect publish/release patterns; emit typed Actions/Intents."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_readiness_insights_protocol.ontology.bootstrap import (
    Ambiguity,
    Proposal,
    ProposalEnvelope,
)
from agent_readiness_insights_protocol.ontology.types import Lifecycle, LifecycleState

from agent_readiness.ontology.loader import load_ontology


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_ACTION_PATTERNS: dict[str, list[str]] = {
    "publish.pypi": [r"twine\s+upload", r"pypa/gh-action-pypi-publish"],
    "publish.npm": [r"npm\s+publish", r"JS-DevTools/npm-publish"],
    "release.tag": [r"\bgit\s+tag\b", r"actions/create-release"],
    "release.github": [r"softprops/action-gh-release", r"\bgh\s+release\s+create\b"],
}


_ACTION_YAML_TEMPLATES: dict[str, dict] = {
    "publish.pypi": {
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ActionType",
        "metadata": {"name": "publish.pypi"},
        "spec": {
            "scope": "single_system",
            "side_effects": [{"kind": "registry_write", "registry": "pypi", "idempotent": False}],
        },
    },
    "publish.npm": {
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ActionType",
        "metadata": {"name": "publish.npm"},
        "spec": {
            "scope": "single_system",
            "side_effects": [{"kind": "registry_write", "registry": "npm", "idempotent": False}],
        },
    },
    "release.tag": {
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ActionType",
        "metadata": {"name": "release.tag"},
        "spec": {
            "scope": "single_system",
            "side_effects": [{"kind": "git_tag", "remote": "origin", "idempotent": False}],
        },
    },
    "release.github": {
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ActionType",
        "metadata": {"name": "release.github"},
        "spec": {
            "scope": "single_system",
            "side_effects": [{"kind": "github_release_create", "idempotent": False}],
        },
    },
}


_INTENT_TEMPLATES: dict[str, dict] = {
    "release_cascade": {
        "apiVersion": "agent-readiness.io/v1",
        "kind": "IntentType",
        "metadata": {"name": "release_cascade"},
        "spec": {
            "scope": "cross_repo",
            "parameters": [
                {"name": "changed_repo", "type": "ref[Repo]", "required": True},
                {"name": "change_kind", "type": "enum[major,minor,patch]", "required": True},
            ],
            "ledger": {
                "location": "ontology/intents/{{ intent_id }}.ledger.jsonl",
                "format": "jsonl",
            },
        },
    },
    "deprecate_repo": {
        "apiVersion": "agent-readiness.io/v1",
        "kind": "IntentType",
        "metadata": {"name": "deprecate_repo"},
        "spec": {
            "scope": "cross_repo",
            "parameters": [{"name": "repo", "type": "ref[Repo]", "required": True}],
            "ledger": {
                "location": "ontology/intents/{{ intent_id }}.ledger.jsonl",
                "format": "jsonl",
            },
        },
    },
    "protocol_breaking_change": {
        "apiVersion": "agent-readiness.io/v1",
        "kind": "IntentType",
        "metadata": {"name": "protocol_breaking_change"},
        "spec": {
            "scope": "cross_repo",
            "parameters": [
                {"name": "protocol", "type": "ref[Protocol]", "required": True},
                {"name": "new_version", "type": "semver", "required": True},
            ],
            "ledger": {
                "location": "ontology/intents/{{ intent_id }}.ledger.jsonl",
                "format": "jsonl",
            },
        },
    },
}


def propose_action_intent_types(workspace: Path, scope: str = "all") -> ProposalEnvelope:
    """Detect Actions from CI workflows and emit Intent templates.

    `scope` is one of: 'all' (default), 'single_system' (Actions only),
    'cross_repo' (Intents only).
    """
    if scope not in {"all", "single_system", "cross_repo"}:
        raise ValueError(f"Unknown scope: {scope!r}")

    detected_action_types: set[str] = set()
    proposed: list[Proposal] = []
    ambiguities: list[Ambiguity] = []

    if scope in ("all", "single_system"):
        ont = load_ontology(workspace / "ontology")
        repos = ont.object_instances.get("Repo", [])
        ratified_repos = [r for r in repos if r.lifecycle.state == LifecycleState.RATIFIED]

        for repo in ratified_repos:
            repo_id = repo.metadata["id"]
            wf_dir = workspace / repo_id / ".github" / "workflows"
            if not wf_dir.is_dir():
                continue
            for wf in wf_dir.glob("*.yml"):
                try:
                    text = wf.read_text()
                except (OSError, UnicodeDecodeError):
                    continue
                for action_name, patterns in _ACTION_PATTERNS.items():
                    for pat in patterns:
                        if re.search(pat, text):
                            detected_action_types.add(action_name)
                            break

        actions_dir = workspace / "ontology" / "actionTypes"
        actions_dir.mkdir(parents=True, exist_ok=True)
        for action_name in sorted(detected_action_types):
            out = actions_dir / f"{action_name}.yaml"
            out.write_text(yaml.safe_dump(_ACTION_YAML_TEMPLATES[action_name], sort_keys=False))
            proposed.append(Proposal(
                id=action_name,
                properties={
                    "path": str(out.relative_to(workspace)),
                    "kind": "ActionType",
                },
                lifecycle=Lifecycle(
                    state=LifecycleState.PROPOSED,
                    proposed_by="bootstrap-mcp",
                    proposed_at=_now(),
                    confidence=0.80,
                    markers=[],
                ),
            ))

    if scope in ("all", "cross_repo"):
        intents_dir = workspace / "ontology" / "intentTypes"
        intents_dir.mkdir(parents=True, exist_ok=True)
        for intent_name, template in _INTENT_TEMPLATES.items():
            out = intents_dir / f"{intent_name}.yaml"
            if out.exists():
                ambiguities.append(Ambiguity(
                    id=intent_name,
                    reason=f"intentTypes/{intent_name}.yaml already present; skipped",
                ))
                continue
            out.write_text(yaml.safe_dump(template, sort_keys=False))
            proposed.append(Proposal(
                id=intent_name,
                properties={
                    "path": str(out.relative_to(workspace)),
                    "kind": "IntentType",
                },
                lifecycle=Lifecycle(
                    state=LifecycleState.PROPOSED,
                    proposed_by="bootstrap-mcp",
                    proposed_at=_now(),
                    confidence=0.85,
                    markers=[],
                ),
            ))

    return ProposalEnvelope(
        tool="bootstrap.propose_action_intent_types",
        target_type=scope,
        proposed=proposed,
        ambiguities=ambiguities,
    )
