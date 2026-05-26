"""Tests for ``agent_readiness.rules_eval.loader``.

Loader behaviours covered elsewhere:
- ``applies_when`` selector: ``tests/rules_eval/test_applies_when.py``
- per-matcher tests: ``tests/rules_eval/matchers/``
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from agent_readiness.rules_eval.loader import RuleLoadError, load_rule_file


def _write(path: Path, body: str) -> Path:
    path.write_text(dedent(body))
    return path


def test_loader_surfaces_namespace_when_present(tmp_path: Path) -> None:
    rule = _write(
        tmp_path / "rule.yaml",
        """\
        rules_version: 2
        id: ontology.fake_for_test
        provenance: agent-readiness/ontology.fake_for_test
        pillar: ontology
        namespace: schema
        title: fake
        match:
          type: path_glob
          require_globs: ["ontology/"]
        action:
          kind: create_file
          path: ontology/README.md
          template: "x"
        verify:
          command: "test -d ontology"
        """,
    )
    loaded = load_rule_file(rule)
    assert loaded is not None
    assert loaded.namespace == "schema"


def test_loader_accepts_validation_namespace(tmp_path: Path) -> None:
    rule = _write(
        tmp_path / "rule.yaml",
        """\
        rules_version: 2
        id: ontology.fake_validation
        provenance: agent-readiness/ontology.fake_validation
        pillar: ontology
        namespace: validation
        title: fake
        match:
          type: path_glob
          require_globs: ["ontology/"]
        action:
          kind: create_file
          path: ontology/README.md
          template: "x"
        verify:
          command: "test -d ontology"
        """,
    )
    loaded = load_rule_file(rule)
    assert loaded is not None
    assert loaded.namespace == "validation"


def test_loader_namespace_defaults_to_none(tmp_path: Path) -> None:
    rule = _write(
        tmp_path / "rule.yaml",
        """\
        rules_version: 2
        id: cognitive_load.fake_for_test
        provenance: agent-readiness/cognitive_load.fake_for_test
        pillar: cognitive_load
        title: fake
        match:
          type: file_size
        action:
          kind: create_file
          path: x
          template: "x"
        verify:
          command: "true"
        """,
    )
    loaded = load_rule_file(rule)
    assert loaded is not None
    assert loaded.namespace is None


def test_loader_rejects_unknown_namespace_value(tmp_path: Path) -> None:
    """Loader fails fast on typos so they don't silently fall through to None."""
    rule = _write(
        tmp_path / "rule.yaml",
        """\
        rules_version: 2
        id: ontology.fake_bad_namespace
        provenance: agent-readiness/ontology.fake_bad_namespace
        pillar: ontology
        namespace: inference
        title: fake
        match:
          type: path_glob
          require_globs: ["x"]
        action:
          kind: create_file
          path: x
          template: "x"
        verify:
          command: "true"
        """,
    )
    with pytest.raises(RuleLoadError, match="namespace"):
        load_rule_file(rule)
