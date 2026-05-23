"""CLI smoke tests for `agent-readiness workspace-scan`."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from agent_readiness.cli import cli


def _make_git(p: Path) -> None:
    (p / ".git").mkdir(parents=True, exist_ok=True)


def _make_child(tmp_path: Path, name: str) -> Path:
    child = tmp_path / name
    _make_git(child)
    (child / "README.md").write_text(f"# {name}")
    return child


def test_workspace_scan_json_emits_envelope(tmp_path: Path) -> None:
    a = _make_child(tmp_path, "a")
    b = _make_child(tmp_path, "b")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["workspace-scan", str(tmp_path),
              f"--children={a},{b}", "--json"],
    )
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["kind"] == "workspace_readiness"
    assert envelope["schema"] == 1
    pillar_names = {p["pillar"] for p in envelope["pillars"]}
    assert pillar_names == {
        "cognitive_load", "feedback", "flow", "safety", "coordination",
    }


def test_workspace_scan_empty_children_exit_3(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["workspace-scan", str(tmp_path)])
    assert result.exit_code == 3


def test_workspace_scan_missing_path_exit_2(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["workspace-scan", str(tmp_path / "nope"),
              "--children=/tmp/x"],
    )
    assert result.exit_code == 2
