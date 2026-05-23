"""Smoke tests for the workspace-scan dataclasses added by the
Coordination spec. Just shape + to_dict() — full behavior tests live
in test_workspace_scan.py."""
from __future__ import annotations

from pathlib import Path

from agent_readiness.models import (
    ChildEnumeration,
    EnumerationReport,
    Pillar,
    WorkspaceReadinessReport,
)


def test_coordination_pillar_exists() -> None:
    assert Pillar.COORDINATION.value == "coordination"


def test_enumeration_report_to_dict_round_trip() -> None:
    rep = EnumerationReport(
        root=ChildEnumeration(
            path=Path("/tmp/ws"),
            has_git=False,
            has_readme=False,
            has_agents_md=True,
            top_files=["AGENTS.md"],
            top_dirs=["a", "b"],
            language_hint=[],
        ),
        children=[
            ChildEnumeration(
                path=Path("/tmp/ws/a"),
                has_git=True,
                has_readme=True,
                has_agents_md=False,
                top_files=["README.md", "pyproject.toml"],
                top_dirs=[],
                language_hint=["python"],
            ),
        ],
        manifest_signals={"pnpm_workspace": False, "cargo_workspace": False,
                          "pyproject_workspace": False,
                          "package_json_workspaces": False, "gradle_multi": False},
        stats={"children_scanned": 1, "children_with_git": 1,
               "children_with_readme": 1, "scan_truncated": False},
    )
    d = rep.to_dict()
    assert d["kind"] == "enumeration"
    assert d["schema"] == 1
    assert d["root"]["has_agents_md"] is True
    assert d["children"][0]["language_hint"] == ["python"]
    assert d["manifest_signals"]["pnpm_workspace"] is False
    assert d["stats"]["scan_truncated"] is False


def test_workspace_report_to_dict_shape() -> None:
    rep = WorkspaceReadinessReport(
        repo_path=Path("/tmp/ws"),
        overall_score=72.5,
        pillar_scores={
            "cognitive_load": 80.0,
            "feedback":       70.0,
            "flow":           75.0,
            "safety":         80.0,
            "coordination":   58.0,
        },
        children=[],
        coordination_findings=[],
        top_action=None,
        stats={"children_scanned": 0, "children_failed": 0,
               "children_failed_paths": [], "scan_duration_ms": 0},
        safety_caps_applied=[],
    )
    d = rep.to_dict()
    assert d["kind"] == "workspace_readiness"
    assert d["schema"] == 1
    assert d["overall_score"] == 72.5
    assert {p["pillar"] for p in d["pillars"]} == {
        "cognitive_load", "feedback", "flow", "safety", "coordination"
    }
