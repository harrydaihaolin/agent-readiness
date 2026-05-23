"""CLI smoke tests for `agent-readiness enumerate`."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from agent_readiness.cli import cli


def _make_git(p: Path) -> None:
    (p / ".git").mkdir(parents=True, exist_ok=True)


def test_enumerate_json_emits_envelope(tmp_path: Path) -> None:
    _make_git(tmp_path / "a")
    (tmp_path / "a" / "README.md").write_text("# a")
    runner = CliRunner()
    result = runner.invoke(cli, ["enumerate", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["kind"] == "enumeration"
    assert envelope["schema"] == 1
    assert envelope["root"]["has_git"] is False
    assert {c["path"].split("/")[-1] for c in envelope["children"]} == {"a"}


def test_enumerate_human_default(tmp_path: Path) -> None:
    _make_git(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["enumerate", str(tmp_path)])
    assert result.exit_code == 0
    assert "root" in result.output.lower() or "children" in result.output.lower()


def test_enumerate_missing_path_exits_2(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["enumerate", str(tmp_path / "does_not_exist")])
    assert result.exit_code == 2


def test_enumerate_path_is_file_exits_2(tmp_path: Path) -> None:
    f = tmp_path / "regular.txt"
    f.write_text("hi")
    runner = CliRunner()
    result = runner.invoke(cli, ["enumerate", str(f)])
    assert result.exit_code == 2
