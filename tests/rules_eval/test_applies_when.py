from __future__ import annotations

from pathlib import Path

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval.applies_when import rule_applies

from tests.rules_eval.matchers.conftest import scaffold_ratified_ontology


def test_is_workspace_true_when_two_git_children(tmp_path: Path):
    for name in ("repo-a", "repo-b"):
        d = tmp_path / name
        d.mkdir()
        (d / ".git").mkdir()
    ctx = RepoContext(root=tmp_path)
    assert rule_applies({"is_workspace": True}, ctx) is True


def test_is_workspace_false_on_single_repo(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    ctx = RepoContext(root=tmp_path)
    assert rule_applies({"is_workspace": True}, ctx) is False
    assert rule_applies({"is_workspace": False}, ctx) is True


def test_has_ontology_true_when_yaml_present(tmp_path: Path):
    scaffold_ratified_ontology(tmp_path, repos=["foo"])
    ctx = RepoContext(root=tmp_path)
    assert rule_applies({"has_ontology": True}, ctx) is True


def test_has_ontology_false_when_missing(tmp_path: Path):
    ctx = RepoContext(root=tmp_path)
    assert rule_applies({"has_ontology": True}, ctx) is False
    assert rule_applies({"has_ontology": False}, ctx) is True


def test_has_ontology_false_when_empty_dir(tmp_path: Path):
    (tmp_path / "ontology").mkdir()
    ctx = RepoContext(root=tmp_path)
    assert rule_applies({"has_ontology": True}, ctx) is False
