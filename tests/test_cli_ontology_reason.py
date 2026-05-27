"""``agent-readiness ontology reason`` CLI (Bundle C).

Surface contract:

* Default invocation loads the workspace ontology, runs every
  registered evaluator, and prints JSON with a ``violations`` list.
* ``--rule <id>`` runs only the named evaluator.
* ``--ontology-root <path>`` overrides the directory; absent, the
  CLI looks for ``<workspace>/ontology`` then
  ``<workspace>/agent-readiness-manifest/ontology``.
* Always exits 0 — the CLI's job is to surface violations, not gate
  on them. Scoring lives in ``agent-readiness scan`` via the
  ``ontology.inference.*`` rules.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from agent_readiness.cli import cli


def _write_self_loop_ontology(root: Path) -> None:
    """Create ``<root>/ontology`` with one ratified dependsOn self-loop."""
    inst_dir = root / "ontology" / "instances" / "dependsOn"
    inst_dir.mkdir(parents=True)
    (inst_dir / "loop.yaml").write_text(
        yaml.safe_dump(
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
            sort_keys=False,
        )
    )


def test_no_ontology_dir_returns_warning_payload(tmp_path: Path) -> None:
    """Calling ``reason`` from a workspace with no ontology/ returns
    an empty violations list plus a ``warning`` field — and exits 0."""
    runner = CliRunner()
    result = runner.invoke(cli, ["ontology", "reason", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["violations"] == []
    assert "warning" in payload
    assert "registered_rules" in payload
    assert any(
        r.startswith("ontology.inference.") for r in payload["registered_rules"]
    )


def test_default_runs_all_evaluators(tmp_path: Path) -> None:
    _write_self_loop_ontology(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["ontology", "reason", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rule_filter"] is None
    assert any(
        v["rule_id"] == "ontology.inference.irreflexive_dependsOn"
        for v in payload["violations"]
    )


def test_rule_filter_runs_only_one_evaluator(tmp_path: Path) -> None:
    _write_self_loop_ontology(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "ontology",
            "reason",
            str(tmp_path),
            "--rule",
            "ontology.inference.irreflexive_dependsOn",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rule_filter"] == "ontology.inference.irreflexive_dependsOn"
    assert len(payload["violations"]) == 1
    assert payload["violations"][0]["severity"] == "error"


def test_ontology_root_override(tmp_path: Path) -> None:
    """The override lets you point at any ontology/ directory,
    independent of workspace layout."""
    custom = tmp_path / "elsewhere"
    custom.mkdir()
    _write_self_loop_ontology(custom)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "ontology",
            "reason",
            str(tmp_path),
            "--ontology-root",
            str(custom / "ontology"),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ontology_root"] == str(custom / "ontology")
    assert len(payload["violations"]) == 1


def test_exit_code_is_zero_even_with_violations(tmp_path: Path) -> None:
    _write_self_loop_ontology(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["ontology", "reason", str(tmp_path)])
    assert result.exit_code == 0
