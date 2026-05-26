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


# ---------------------------------------------------------------------------
# Per-rule confidence (Bundle B / protocol v0.9.0)
# ---------------------------------------------------------------------------


def test_loader_confidence_defaults_to_medium(tmp_path: Path) -> None:
    """Mirrors protocol default — unannotated rules behave like medium.

    With ``confidence: medium`` the engine's ``apply_top_action`` will
    return a ``confirm_required`` envelope instead of mutating, which
    is the safe default for the existing rule set until each rule is
    explicitly audited up to ``high`` (PR B-4).
    """
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
    assert loaded.confidence == "medium"


def test_loader_confidence_accepts_high(tmp_path: Path) -> None:
    rule = _write(
        tmp_path / "rule.yaml",
        """\
        rules_version: 2
        id: cognitive_load.fake_high
        provenance: agent-readiness/cognitive_load.fake_high
        pillar: cognitive_load
        confidence: high
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
    assert loaded.confidence == "high"


def test_loader_confidence_accepts_low(tmp_path: Path) -> None:
    rule = _write(
        tmp_path / "rule.yaml",
        """\
        rules_version: 2
        id: ontology.fake_low
        provenance: agent-readiness/ontology.fake_low
        pillar: ontology
        confidence: low
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
    assert loaded.confidence == "low"


def test_loader_rejects_unknown_confidence_value(tmp_path: Path) -> None:
    """Closed-world contract: typos must fail loudly, not coerce to default."""
    rule = _write(
        tmp_path / "rule.yaml",
        """\
        rules_version: 2
        id: ontology.fake_bad_confidence
        provenance: agent-readiness/ontology.fake_bad_confidence
        pillar: ontology
        confidence: certain
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
    with pytest.raises(RuleLoadError, match="confidence"):
        load_rule_file(rule)
