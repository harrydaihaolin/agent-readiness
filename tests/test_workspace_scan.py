"""Tests for agent_readiness.workspace_scan.scan().

This file covers the orchestration + aggregation + top_action behavior.
Per-check correctness lives in test_coordination.py; per-repo scan
behavior is tested in the existing scanner tests.
"""
from __future__ import annotations

from pathlib import Path

from agent_readiness.models import (
    ChildReadiness,
    Finding,
    Pillar,
    Severity,
    WorkspaceReadinessReport,
)
from agent_readiness.workspace_scan import (
    _aggregate_pillar_scores,
    _pick_top_action,
    scan,
)
from tests.rules_eval.matchers.conftest import scaffold_ratified_ontology


def _make_git(p: Path) -> None:
    (p / ".git").mkdir(parents=True, exist_ok=True)


def _make_child_repo(tmp_path: Path, name: str) -> Path:
    child = tmp_path / name
    _make_git(child)
    (child / "README.md").write_text(f"# {name}")
    return child


# --- orchestration ------------------------------------------------------

def test_scan_runs_coordination_at_root(tmp_path: Path) -> None:
    _make_git(tmp_path / "a")
    (tmp_path / "a" / "README.md").write_text("a")
    _make_git(tmp_path / "b")
    (tmp_path / "b" / "README.md").write_text("b")
    result = scan(tmp_path, children=[tmp_path / "a", tmp_path / "b"])
    assert isinstance(result, WorkspaceReadinessReport)
    coordination_check_ids = {f.check_id for f in result.coordination_findings}
    assert "coordination.root_agents_md" in coordination_check_ids
    assert "coordination.repos_manifest" in coordination_check_ids
    assert "coordination.dep_graph" in coordination_check_ids


def test_scan_fans_out_to_each_child(tmp_path: Path) -> None:
    a = _make_child_repo(tmp_path, "a")
    b = _make_child_repo(tmp_path, "b")
    result = scan(tmp_path, children=[a, b])
    assert {c.path.name for c in result.children} == {"a", "b"}


def test_scan_with_empty_children_raises(tmp_path: Path) -> None:
    try:
        scan(tmp_path, children=[])
    except ValueError as exc:
        assert "children" in str(exc).lower()
        return
    raise AssertionError("expected ValueError on empty children")


def test_scan_handles_missing_child_path(tmp_path: Path) -> None:
    a = _make_child_repo(tmp_path, "a")
    bogus = tmp_path / "does_not_exist"
    result = scan(tmp_path, children=[a, bogus])
    assert result.stats["children_failed"] == 1
    assert str(bogus.resolve()) in result.stats["children_failed_paths"]
    assert len(result.children) == 1
    assert result.children[0].path.name == "a"


def test_scan_envelope_to_dict_shape(tmp_path: Path) -> None:
    a = _make_child_repo(tmp_path, "a")
    result = scan(tmp_path, children=[a])
    d = result.to_dict()
    assert d["kind"] == "workspace_readiness"
    assert d["schema"] == 1
    pillar_names = {p["pillar"] for p in d["pillars"]}
    assert pillar_names == {
        "cognitive_load", "feedback", "flow", "safety",
        "coordination", "ontology",
    }
    for p in d["pillars"]:
        if p["pillar"] in ("coordination", "ontology"):
            assert p["source"] == "workspace"
        else:
            assert p["source"] == "aggregated"


# --- aggregation + top_action ------------------------------------------

def test_aggregate_is_arithmetic_mean() -> None:
    child_a = ChildReadiness(
        path=Path("/a"), overall_score=80.0,
        pillar_scores={"feedback": 80.0, "flow": 60.0,
                       "cognitive_load": 70.0, "safety": 90.0},
    )
    child_b = ChildReadiness(
        path=Path("/b"), overall_score=70.0,
        pillar_scores={"feedback": 60.0, "flow": 100.0,
                       "cognitive_load": 50.0, "safety": 50.0},
    )
    out = _aggregate_pillar_scores([child_a, child_b], ontology_score=10.0)
    assert out["feedback"] == 70.0
    assert out["flow"] == 80.0
    assert out["cognitive_load"] == 60.0
    assert out["safety"] == 70.0
    assert out["ontology"] == 10.0
    assert out["coordination"] == 10.0
    assert out["coordination"] == out["ontology"]


def test_top_action_coordination_beats_child() -> None:
    """A coordination warn finding beats any child's top_action."""
    coord_finding = Finding(
        check_id="coordination.dep_graph", pillar=Pillar.COORDINATION,
        message="x", severity=Severity.WARN,
        action={"kind": "append_to_file", "path": "AGENTS.md", "content": ""},
        verify={"command": "rg ..."},
    )
    child = ChildReadiness(
        path=Path("/a"), overall_score=10.0,
        pillar_scores={"feedback": 10.0, "flow": 10.0,
                       "cognitive_load": 10.0, "safety": 10.0},
        top_action={"check_id": "feedback.bad", "pillar": "feedback",
                    "severity": "warn", "message": "x", "action": None,
                    "verify": None},
    )
    top = _pick_top_action([coord_finding], [child])
    assert top is not None
    assert top["scope"] == "workspace"
    assert top["check_id"] == "coordination.dep_graph"


def test_top_action_no_coordination_picks_worst_child() -> None:
    child_high = ChildReadiness(
        path=Path("/a"), overall_score=80.0,
        pillar_scores={"feedback": 80.0, "flow": 80.0,
                       "cognitive_load": 80.0, "safety": 80.0},
        top_action={"check_id": "x.high", "pillar": "flow",
                    "severity": "warn", "message": "m"},
    )
    child_low = ChildReadiness(
        path=Path("/b"), overall_score=20.0,
        pillar_scores={"feedback": 20.0, "flow": 20.0,
                       "cognitive_load": 20.0, "safety": 20.0},
        top_action={"check_id": "x.low", "pillar": "flow",
                    "severity": "warn", "message": "m"},
    )
    top = _pick_top_action([], [child_high, child_low])
    assert top is not None
    assert top["scope"] == "child"
    assert top["check_id"] == "x.low"
    assert "b" in str(top.get("child_path", ""))


def test_top_action_no_findings_and_no_top_actions_returns_none() -> None:
    child = ChildReadiness(
        path=Path("/a"), overall_score=100.0,
        pillar_scores={"feedback": 100.0, "flow": 100.0,
                       "cognitive_load": 100.0, "safety": 100.0},
        top_action=None,
    )
    assert _pick_top_action([], [child]) is None


def test_workspace_scan_emits_ontology_and_coordination_alias(tmp_path: Path) -> None:
    a = _make_child_repo(tmp_path, "a")
    b = _make_child_repo(tmp_path, "b")
    scaffold_ratified_ontology(tmp_path, repos=["a", "b"])
    (tmp_path / "ontology" / "actionTypes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ontology" / "actionTypes" / "publish.pypi.yaml").write_text(
        "apiVersion: agent-readiness.io/v1\nkind: ActionType\n"
        "metadata:\n  name: publish.pypi\nspec: {}\n"
    )
    (tmp_path / "ontology" / "intentTypes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ontology" / "intentTypes" / "release_cascade.yaml").write_text(
        "apiVersion: agent-readiness.io/v1\nkind: IntentType\n"
        "metadata:\n  name: release_cascade\nspec: {}\n"
    )
    result = scan(tmp_path, children=[a, b])
    assert "ontology" in result.pillar_scores
    assert "coordination" in result.pillar_scores
    assert result.pillar_scores["ontology"] == result.pillar_scores["coordination"]
