"""Tests for the v1 Coordination pillar checks."""
from __future__ import annotations

from pathlib import Path

from agent_readiness.coordination import (
    check_dep_graph,
    check_repos_manifest,
    check_root_agents_md,
    evaluate_coordination,
)
from agent_readiness.models import Pillar, Severity


# --- coordination.root_agents_md ----------------------------------------

def test_root_agents_md_present_passes(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# how agents work in this workspace\n")
    result = check_root_agents_md(tmp_path, children=[])
    assert result.score == 100.0
    assert result.findings == []
    assert result.pillar is Pillar.COORDINATION


def test_root_agents_md_missing_fires(tmp_path: Path) -> None:
    result = check_root_agents_md(tmp_path, children=[])
    assert result.score == 0.0
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.check_id == "coordination.root_agents_md"
    assert f.severity is Severity.WARN
    assert f.action is not None
    assert f.action["kind"] == "create_file"


def test_root_agents_md_empty_treated_as_missing(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("   \n   \n")
    result = check_root_agents_md(tmp_path, children=[])
    assert result.score == 0.0
    assert len(result.findings) == 1


def test_root_agents_md_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "agents.md").write_text("# agents")
    result = check_root_agents_md(tmp_path, children=[])
    assert result.score == 100.0


def test_evaluate_coordination_aggregates_v1_checks(tmp_path: Path) -> None:
    """The orchestrator runs all three v1 checks and returns a list."""
    results = evaluate_coordination(tmp_path, children=[tmp_path / "child"])
    check_ids = {r.check_id for r in results}
    assert check_ids == {
        "coordination.root_agents_md",
        "coordination.repos_manifest",
        "coordination.dep_graph",
    }


# --- coordination.repos_manifest ----------------------------------------

def test_repos_manifest_pnpm_workspace_passes(tmp_path: Path) -> None:
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n")
    result = check_repos_manifest(tmp_path, children=[tmp_path / "a"])
    assert result.score == 100.0


def test_repos_manifest_repos_yaml_passes(tmp_path: Path) -> None:
    (tmp_path / "repos.yaml").write_text("repos:\n  - name: a\n")
    result = check_repos_manifest(tmp_path, children=[tmp_path / "a"])
    assert result.score == 100.0


def test_repos_manifest_agents_md_enumerates_passes(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "# workspace\n\n## Repos in this workspace\n\n- a\n- b\n"
    )
    result = check_repos_manifest(tmp_path, children=[tmp_path / "a", tmp_path / "b"])
    assert result.score == 100.0


def test_repos_manifest_missing_fires(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# workspace\n\n")  # no enumeration
    result = check_repos_manifest(tmp_path, children=[tmp_path / "a", tmp_path / "b"])
    assert result.score == 0.0
    assert result.findings[0].check_id == "coordination.repos_manifest"
    assert result.findings[0].severity is Severity.WARN


# --- coordination.dep_graph ---------------------------------------------

def test_dep_graph_workspace_graph_md_passes(tmp_path: Path) -> None:
    (tmp_path / "WORKSPACE_GRAPH.md").write_text("# graph")
    result = check_dep_graph(tmp_path, children=[])
    assert result.score == 100.0


def test_dep_graph_agents_md_change_order_passes(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "# workspace\n\n## Change order\n\n1. shared-libs\n2. backend\n"
    )
    result = check_dep_graph(tmp_path, children=[])
    assert result.score == 100.0


def test_dep_graph_agents_md_depends_on_passes(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "## Dependency graph\n\n- backend depends_on shared-libs\n"
    )
    result = check_dep_graph(tmp_path, children=[])
    assert result.score == 100.0


def test_dep_graph_pnpm_workspace_passes(tmp_path: Path) -> None:
    """A workspace manifest with explicit packages list counts as a dep graph."""
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n  - 'libs/*'\n")
    result = check_dep_graph(tmp_path, children=[])
    assert result.score == 100.0


def test_dep_graph_missing_fires(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# workspace with no deps documented")
    result = check_dep_graph(tmp_path, children=[])
    assert result.score == 0.0
    assert result.findings[0].check_id == "coordination.dep_graph"
    assert result.findings[0].severity is Severity.WARN
