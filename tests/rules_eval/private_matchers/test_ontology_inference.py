"""Tests for the ``ontology_inference`` private matcher (Bundle C).

Bridges YAML rules in ``agent-readiness-rules`` under
``rules/ontology/inference/`` to the forward chainer in
``agent_readiness.ontology.reasoning``. Each ``inference`` rule
references this matcher and passes its own ``rule_id`` in the
config so the matcher knows which evaluator to delegate to.

These tests use the explicit ``ontology_root`` override (instead of
the discovery fallback to ``<ctx.root>/ontology``) so the fixture
directory layout stays minimal — RepoContext only requires the root
to exist and be a directory.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval.private_matchers.ontology_inference import (
    match_ontology_inference,
)


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False))


def _make_minimal_ontology(root: Path) -> Path:
    """Write a small ontology/ tree that trips one evaluator.

    Includes a single dependsOn self-loop so the
    irreflexive_dependsOn rule fires; nothing else is set up.
    """
    ont_dir = root / "ontology"
    _write_yaml(
        ont_dir / "instances" / "dependsOn" / "self-loop.yaml",
        {
            "apiVersion": "agent-readiness.io/v1",
            "kind": "LinkInstance",
            "metadata": {
                "link_type": "dependsOn",
                "id": "a--dependsOn--a",
            },
            "spec": {
                "from": {"object_type": "Repo", "id": "a"},
                "to": {"object_type": "Repo", "id": "a"},
            },
            "lifecycle": {
                "state": "ratified",
                "proposed_by": "test",
                "proposed_at": "2026-05-26T00:00:00+00:00",
                "confidence": 1.0,
                "markers": [],
                "ratified_by": "test",
                "ratified_at": "2026-05-26T00:00:00+00:00",
            },
        },
    )
    return ont_dir


def test_missing_rule_id_returns_no_findings(tmp_path: Path) -> None:
    """Defensive: a YAML rule that forgot to pass ``rule_id`` in
    its match config shouldn't crash the scan."""
    ctx = RepoContext(root=tmp_path)
    assert match_ontology_inference(ctx, {}) == []


def test_no_ontology_directory_returns_no_findings(tmp_path: Path) -> None:
    """When the workspace has no ontology/ at all, the matcher
    silently emits nothing — same contract as gaps_jsonl_unresolved."""
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_inference(
        ctx, {"rule_id": "ontology.inference.irreflexive_dependsOn"}
    )
    assert findings == []


def test_fires_for_known_violation(tmp_path: Path) -> None:
    """End-to-end: write an ontology with a self-loop, point the
    matcher at it, and verify the violation surfaces as a finding."""
    ont_dir = _make_minimal_ontology(tmp_path)
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_inference(
        ctx,
        {
            "rule_id": "ontology.inference.irreflexive_dependsOn",
            "ontology_root": str(ont_dir),
        },
    )
    assert len(findings) == 1
    file_, line_, msg = findings[0]
    assert file_ is None and line_ is None
    assert "depends on itself" in msg


def test_unknown_rule_id_silent(tmp_path: Path) -> None:
    """A YAML rule referring to an evaluator that doesn't exist
    yet must not crash the scan."""
    ont_dir = _make_minimal_ontology(tmp_path)
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_inference(
        ctx,
        {
            "rule_id": "ontology.inference.not_registered",
            "ontology_root": str(ont_dir),
        },
    )
    assert findings == []


def test_relative_ontology_root_resolved_against_ctx_root(tmp_path: Path) -> None:
    """``ontology_root`` may be a workspace-relative path."""
    _make_minimal_ontology(tmp_path)
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_inference(
        ctx,
        {
            "rule_id": "ontology.inference.irreflexive_dependsOn",
            "ontology_root": "ontology",  # relative
        },
    )
    assert len(findings) == 1


def test_fallback_discovery_in_repo_layout(tmp_path: Path) -> None:
    """With no override, the matcher discovers ``<root>/ontology``."""
    _make_minimal_ontology(tmp_path)
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_inference(
        ctx,
        {"rule_id": "ontology.inference.irreflexive_dependsOn"},
    )
    assert len(findings) == 1


def test_malformed_ontology_does_not_crash(tmp_path: Path) -> None:
    """A malformed ontology yaml exits cleanly with no findings, not
    a tracebacked scan."""
    ont_dir = tmp_path / "ontology"
    (ont_dir / "instances" / "dependsOn").mkdir(parents=True)
    (ont_dir / "instances" / "dependsOn" / "bogus.yaml").write_text("not: a: link")
    ctx = RepoContext(root=tmp_path)
    findings = match_ontology_inference(
        ctx,
        {
            "rule_id": "ontology.inference.irreflexive_dependsOn",
            "ontology_root": str(ont_dir),
        },
    )
    assert findings == []
