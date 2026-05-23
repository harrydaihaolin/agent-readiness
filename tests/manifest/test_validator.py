"""Tests for agent_readiness.manifest.validator."""
from __future__ import annotations

from pathlib import Path

import yaml

from agent_readiness.manifest.validator import (
    ValidationResult,
    validate_manifest_dir,
)


def _write_minimal_manifest(root: Path) -> None:
    (root / "manifest.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "WorkspaceManifest",
        "metadata": {
            "name": "t",
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
    (root / ".agent-readiness-version").write_text(">=0.5.0,<1.0.0\n")


def test_validate_clean_manifest_passes(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    result: ValidationResult = validate_manifest_dir(tmp_path)
    assert result.valid is True
    assert result.issues == []
    assert result.api_version == "agent-readiness.io/v1"
    assert result.manifest_name == "t"


def test_validate_missing_file_returns_issue(tmp_path: Path) -> None:
    (tmp_path / "glossary.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "Glossary",
        "spec": {"terms": [], "exceptions": []},
    }))
    result = validate_manifest_dir(tmp_path)
    assert result.valid is False
    assert any("manifest.yaml" in i.message for i in result.issues)


def test_validate_schema_error_carries_location(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    bad_rule = tmp_path / "rules" / "001-bad.yaml"
    bad_rule.write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ArchRule",
        "metadata": {"id": "001-bad", "severity": "PURPLE"},
        "spec": {"description": "x", "selector": {},
                 "assert": {"file_exists": "x"}},
    }))
    result = validate_manifest_dir(tmp_path)
    assert result.valid is False
    assert any("001-bad.yaml" in i.location for i in result.issues)


def test_validate_tag_used_in_repo_must_exist_in_axes(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    (tmp_path / "boundaries.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "Boundaries",
        "spec": {
            "tagAxes": {"scope": ["protocol", "service"]},
            "rules": [
                {"name": "x", "from": {"tier": "edge"},
                 "to": {"tier": "internal"}, "effect": "deny"},
                {"name": "default", "effect": "allow"},
            ],
        },
    }))
    result = validate_manifest_dir(tmp_path)
    assert result.valid is False
    assert any("tier" in i.message for i in result.issues)


def test_validate_arch_rule_id_must_match_filename_prefix(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    (tmp_path / "rules" / "001-foo.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ArchRule",
        "metadata": {"id": "999-bar", "severity": "error"},
        "spec": {"description": "x", "selector": {},
                 "assert": {"file_exists": "x"}},
    }))
    result = validate_manifest_dir(tmp_path)
    assert result.valid is False
    assert any(
        "001-foo.yaml" in i.location and "999-bar" in i.message
        for i in result.issues
    )


def test_validate_result_emits_json_envelope(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    result = validate_manifest_dir(tmp_path)
    envelope = result.to_json_envelope()
    assert envelope["apiVersion"] == "agent-readiness.io/v1"
    assert envelope["kind"] == "ManifestValidationResult"
    assert envelope["summary"]["valid"] is True
    assert envelope["issues"] == []
    assert envelope["summary"]["manifest_name"] == "t"
