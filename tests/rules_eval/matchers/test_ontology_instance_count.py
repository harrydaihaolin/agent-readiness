from __future__ import annotations

from pathlib import Path

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval.matchers.ontology_instance_count import match_ontology_instance_count

from tests.rules_eval.matchers.conftest import scaffold_ratified_ontology


def test_passes_when_count_meets_minimum(tmp_path: Path):
    scaffold_ratified_ontology(tmp_path, repos=["a", "b", "c"])
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_instance_count(
        ctx, {"object_type": "Repo", "min": 2, "state": "ratified"}
    )
    assert findings == []


def test_fails_when_count_below_minimum(tmp_path: Path):
    scaffold_ratified_ontology(tmp_path, repos=["a"])
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_instance_count(
        ctx, {"object_type": "Repo", "min": 2, "state": "ratified"}
    )
    assert findings
    assert "1/2" in findings[0][2]
