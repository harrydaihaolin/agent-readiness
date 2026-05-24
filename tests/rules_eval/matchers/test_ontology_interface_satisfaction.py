from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval.matchers.ontology_interface_satisfaction import (
    match_ontology_interface_satisfaction,
)
from agent_readiness_insights_protocol.ontology.types import Lifecycle, LifecycleState, ObjectInstance

from tests.rules_eval.matchers.conftest import scaffold_ratified_ontology


def _write_repo_with_claims(workspace: Path, repo_id: str, claims: list[dict]) -> None:
    target = workspace / "ontology" / "instances" / "Repo" / f"{repo_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    inst = ObjectInstance(
        apiVersion="agent-readiness.io/v1",
        kind="ObjectInstance",
        metadata={"object_type": "Repo", "id": repo_id},
        spec={"properties": {"name": repo_id}, "implements": claims},
        lifecycle=Lifecycle(
            state=LifecycleState.RATIFIED,
            proposed_by="test",
            proposed_at=now,
            confidence=1.0,
            markers=[],
            ratified_by="test",
            ratified_at=now,
        ),
    )
    target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))


def test_passes_when_no_failing_claims(tmp_path: Path):
    scaffold_ratified_ontology(tmp_path, repos=["foo"])
    _write_repo_with_claims(tmp_path, "foo", [
        {"interface": "Documented", "satisfaction": "ratified", "last_checked": "2026-01-01T00:00:00Z"},
    ])
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_interface_satisfaction(ctx, {})
    assert findings == []


def test_fails_when_any_claim_is_failing(tmp_path: Path):
    scaffold_ratified_ontology(tmp_path, repos=["foo"])
    _write_repo_with_claims(tmp_path, "foo", [
        {"interface": "Releasable", "satisfaction": "failing", "last_checked": "2026-01-01T00:00:00Z"},
    ])
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_interface_satisfaction(ctx, {})
    assert findings
    assert "failing" in findings[0][2].lower()
    assert "Releasable" in findings[0][2]


def test_interface_scope_filter(tmp_path: Path):
    scaffold_ratified_ontology(tmp_path, repos=["foo"])
    _write_repo_with_claims(tmp_path, "foo", [
        {"interface": "Releasable", "satisfaction": "failing", "last_checked": "2026-01-01T00:00:00Z"},
        {"interface": "Documented", "satisfaction": "failing", "last_checked": "2026-01-01T00:00:00Z"},
    ])
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_interface_satisfaction(ctx, {"interfaces": ["Documented"]})
    assert len(findings) == 1
    assert "Documented" in findings[0][2]
