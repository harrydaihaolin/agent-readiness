from __future__ import annotations

from pathlib import Path

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval.matchers.ontology_ref_closure import match_ontology_ref_closure

from tests.rules_eval.matchers.conftest import scaffold_ratified_ontology


def test_passes_on_well_formed_ontology(tmp_path: Path):
    scaffold_ratified_ontology(
        tmp_path,
        repos=["foo", "bar"],
        links=[("foo", "bar", "dependsOn")],
    )
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_ref_closure(ctx, {"source": "ontology"})
    assert findings == []


def test_fails_on_dangling_link(tmp_path: Path):
    scaffold_ratified_ontology(
        tmp_path,
        repos=["foo"],
        links=[("foo", "missing", "dependsOn")],
    )
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_ref_closure(ctx, {"source": "ontology"})
    assert findings
    message = findings[0][2].lower()
    assert "dangling" in message or "missing" in message


def test_skips_when_no_ontology_dir(tmp_path: Path):
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_ref_closure(ctx, {"source": "ontology"})
    assert findings == []
