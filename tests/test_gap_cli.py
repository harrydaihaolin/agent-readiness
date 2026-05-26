"""``agent-readiness gap {record,resolve,list}`` CLI (Bundle B / B1).

Surface contract:

* ``record`` writes one row to ``.agent-readiness/gaps.jsonl`` and
  prints the new id.
* ``list`` enumerates unresolved Gap rows by default; ``--all``
  includes resolved ones.
* ``resolve`` flips ``resolved`` on the matching row; returns
  non-zero exit on unknown id.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from agent_readiness.cli import cli


def test_gap_record_creates_jsonl_and_emits_id(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            [
                "gap",
                "record",
                "--kind",
                "ambiguous_object_type",
                "--detail",
                "two candidates match this finding",
                "--severity",
                "medium",
            ],
        )
        assert result.exit_code == 0, result.output
        assert result.output.startswith("recorded gap gap-")

        jsonl = Path(".agent-readiness") / "gaps.jsonl"
        assert jsonl.exists()
        record = json.loads(jsonl.read_text().strip())
        assert record["kind"] == "gap"
        assert record["gap_kind"] == "ambiguous_object_type"
        assert record["severity"] == "medium"
        assert record["resolved"] is False


def test_gap_record_with_candidate_resolutions(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            [
                "gap",
                "record",
                "--kind",
                "missing_manifest_field",
                "--detail",
                "no [project.scripts]",
                "--candidate",
                "add scripts.x = 'pkg.cli:main'",
                "--candidate",
                "rename existing 'console_scripts' entry",
            ],
        )
        assert result.exit_code == 0, result.output
        record = json.loads(
            (Path(".agent-readiness") / "gaps.jsonl").read_text().strip()
        )
        assert record["candidate_resolutions"] == [
            "add scripts.x = 'pkg.cli:main'",
            "rename existing 'console_scripts' entry",
        ]


def test_gap_list_unresolved_only_by_default(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # No file yet -> friendly message.
        result = runner.invoke(cli, ["gap", "list"])
        assert result.exit_code == 0
        assert "no unresolved gaps" in result.output.lower()

        # Record two; the listing shows them both.
        runner.invoke(
            cli, ["gap", "record", "--kind", "k1", "--detail", "d1"]
        )
        runner.invoke(
            cli, ["gap", "record", "--kind", "k2", "--detail", "d2"]
        )
        result = runner.invoke(cli, ["gap", "list"])
        assert result.exit_code == 0
        assert "k1" in result.output and "d1" in result.output
        assert "k2" in result.output and "d2" in result.output


def test_gap_resolve_marks_resolved_and_drops_from_default_list(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(
            cli,
            ["gap", "record", "--kind", "x", "--detail", "to be resolved"],
        )
        record = json.loads(
            (Path(".agent-readiness") / "gaps.jsonl").read_text().strip()
        )
        gap_id = record["id"]

        result = runner.invoke(cli, ["gap", "resolve", gap_id])
        assert result.exit_code == 0
        assert f"resolved {gap_id}" in result.output

        # Default listing no longer surfaces it.
        result = runner.invoke(cli, ["gap", "list"])
        assert "no unresolved gaps" in result.output.lower()

        # --all surfaces it with the resolved marker.
        result = runner.invoke(cli, ["gap", "list", "--all"])
        assert gap_id in result.output
        assert "[x]" in result.output

        # The on-disk row has resolved=True.
        rows = [
            json.loads(line)
            for line in (Path(".agent-readiness") / "gaps.jsonl")
            .read_text()
            .splitlines()
            if line.strip()
        ]
        assert any(r["id"] == gap_id and r["resolved"] is True for r in rows)


def test_gap_resolve_unknown_id_exits_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["gap", "resolve", "gap-does-not-exist"])
        assert result.exit_code != 0
        assert "no such gap" in result.output.lower()
