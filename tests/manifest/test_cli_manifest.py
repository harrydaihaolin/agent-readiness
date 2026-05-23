"""CLI smoke tests for `agent-readiness manifest validate`."""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from agent_readiness.cli import cli


def _write_minimal(root: Path) -> None:
    (root / "manifest.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "WorkspaceManifest",
        "metadata": {
            "name": "demo",
            "version": "1.0.0",
            "compatibleScanner": ">=0.5.0,<1.0.0",
        },
        "spec": {"exemplar": "x", "repos": [], "answers": []},
    }))
    (root / "glossary.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "Glossary",
        "spec": {"terms": [], "exceptions": []},
    }))
    (root / "boundaries.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "Boundaries",
        "spec": {
            "tagAxes": {},
            "rules": [{"name": "default", "effect": "allow"}],
        },
    }))
    (root / "rules").mkdir(exist_ok=True)


def test_manifest_validate_json_envelope(tmp_path: Path) -> None:
    _write_minimal(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["manifest", "validate", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["apiVersion"] == "agent-readiness.io/v1"
    assert envelope["kind"] == "ManifestValidationResult"
    assert envelope["summary"]["valid"] is True
    assert envelope["summary"]["manifest_name"] == "demo"
    assert envelope["issues"] == []


def test_manifest_validate_human_output(tmp_path: Path) -> None:
    _write_minimal(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["manifest", "validate", str(tmp_path)])
    assert result.exit_code == 0
    assert "demo" in result.output
    assert "valid" in result.output


def test_manifest_validate_returns_1_on_errors(tmp_path: Path) -> None:
    _write_minimal(tmp_path)
    (tmp_path / "boundaries.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "Boundaries",
        "spec": {
            "tagAxes": {"scope": ["a", "b"]},
            "rules": [
                {"name": "x", "from": {"tier": "edge"},
                 "to": {"tier": "internal"}, "effect": "deny"},
                {"name": "default", "effect": "allow"},
            ],
        },
    }))
    runner = CliRunner()
    result = runner.invoke(cli, ["manifest", "validate", str(tmp_path), "--json"])
    assert result.exit_code == 1
    envelope = json.loads(result.output)
    assert envelope["summary"]["valid"] is False
    assert envelope["summary"]["errors"] >= 1


def test_manifest_validate_exit_2_on_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    runner = CliRunner()
    result = runner.invoke(cli, ["manifest", "validate", str(missing)])
    assert result.exit_code == 2
    assert "does not exist" in result.output.lower() or "directory" in result.output.lower()
