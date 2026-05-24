"""Tests for agent_readiness.manifest.loader."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_readiness.manifest.loader import (
    LoadedManifest,
    ManifestLoadError,
    load_manifest_dir,
)


def _write_minimal_manifest(root: Path) -> None:
    """Drop a minimal valid manifest tree into the given directory."""
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


def test_load_manifest_dir_minimal(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    m: LoadedManifest = load_manifest_dir(tmp_path)
    assert m.manifest.metadata.name == "t"
    assert m.glossary.spec.terms == []
    assert m.boundaries.spec.rules[0].name == "default"
    assert m.arch_rules == []
    assert m.scanner_version_constraint == ">=0.5.0,<1.0.0"
    assert m.source_dir == tmp_path


def test_load_manifest_dir_with_arch_rules(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    (tmp_path / "rules" / "001-test.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ArchRule",
        "metadata": {"id": "001-test", "severity": "error"},
        "spec": {"description": "x", "selector": {},
                 "assert": {"file_exists": "x"}},
    }))
    (tmp_path / "rules" / "002-test.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ArchRule",
        "metadata": {"id": "002-test", "severity": "warn"},
        "spec": {"description": "y", "selector": {},
                 "assert": {"file_not_exists": "y"}},
    }))
    m = load_manifest_dir(tmp_path)
    assert len(m.arch_rules) == 2
    assert m.arch_rules[0].metadata.id == "001-test"
    assert m.arch_rules[1].metadata.id == "002-test"


def test_load_manifest_dir_missing_manifest_yaml(tmp_path: Path) -> None:
    (tmp_path / "glossary.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "Glossary",
        "spec": {"terms": [], "exceptions": []},
    }))
    with pytest.raises(ManifestLoadError) as excinfo:
        load_manifest_dir(tmp_path)
    assert "manifest.yaml" in str(excinfo.value)


def test_load_manifest_dir_malformed_yaml(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    (tmp_path / "glossary.yaml").write_text("not: valid: yaml: content:")
    with pytest.raises(ManifestLoadError) as excinfo:
        load_manifest_dir(tmp_path)
    assert "glossary.yaml" in (excinfo.value.location or "")


def test_load_manifest_dir_schema_violation(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    (tmp_path / "rules" / "001-bad.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ArchRule",
        "metadata": {"id": "001-bad", "severity": "PURPLE"},
        "spec": {"description": "x", "selector": {},
                 "assert": {"file_exists": "x"}},
    }))
    with pytest.raises(ManifestLoadError) as excinfo:
        load_manifest_dir(tmp_path)
    assert "001-bad.yaml" in (excinfo.value.location or "")


def test_load_manifest_dir_arch_rules_ignores_non_yaml(tmp_path: Path) -> None:
    _write_minimal_manifest(tmp_path)
    (tmp_path / "rules" / "001-test.yaml").write_text(yaml.safe_dump({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ArchRule",
        "metadata": {"id": "001-test", "severity": "error"},
        "spec": {"description": "x", "selector": {},
                 "assert": {"file_exists": "x"}},
    }))
    (tmp_path / "rules" / "README.md").write_text("notes")
    (tmp_path / "rules" / ".gitkeep").write_text("")
    m = load_manifest_dir(tmp_path)
    assert len(m.arch_rules) == 1
