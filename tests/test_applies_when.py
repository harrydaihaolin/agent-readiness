"""Tests for the ``applies_when`` rule selector.

Covers the predicate dispatcher in isolation, plus integration with
the evaluator (a rule whose ``applies_when`` excludes the current
repo must short-circuit to ``not_measured`` and produce zero findings).
"""
from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval.applies_when import rule_applies
from agent_readiness.rules_eval.evaluator import evaluate_rule
from agent_readiness.rules_eval.loader import load_rule_file


# ----------------------------------------------------------------------------
# rule_applies — pure predicate dispatch
# ----------------------------------------------------------------------------


def _ctx_with_pyproject(tmpdir: Path) -> RepoContext:
    (tmpdir / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.1.0'\n")
    return RepoContext(root=tmpdir)


def _ctx_empty(tmpdir: Path) -> RepoContext:
    (tmpdir / "README.md").write_text("yaml-only repo\n")
    return RepoContext(root=tmpdir)


def test_none_means_always_applies(tmp_path: Path) -> None:
    ctx = _ctx_empty(tmp_path)
    assert rule_applies(None, ctx) is True
    assert rule_applies({}, ctx) is True


def test_any_language_detected_true_skips_yaml_only_repo(tmp_path: Path) -> None:
    ctx = _ctx_empty(tmp_path)
    assert ctx.detected_languages == []
    assert rule_applies({"any_language_detected": True}, ctx) is False


def test_any_language_detected_true_runs_on_python_repo(tmp_path: Path) -> None:
    ctx = _ctx_with_pyproject(tmp_path)
    assert "python" in ctx.detected_languages
    assert rule_applies({"any_language_detected": True}, ctx) is True


def test_any_language_detected_false_inverts(tmp_path: Path) -> None:
    """``any_language_detected: false`` runs only on no-language repos."""
    ctx_empty = _ctx_empty(tmp_path)
    assert rule_applies({"any_language_detected": False}, ctx_empty) is True

    with TemporaryDirectory() as td2:
        ctx_py = _ctx_with_pyproject(Path(td2))
        assert rule_applies({"any_language_detected": False}, ctx_py) is False


def test_languages_in_filters_to_listed(tmp_path: Path) -> None:
    ctx = _ctx_with_pyproject(tmp_path)
    assert rule_applies({"languages_in": ["python", "rust"]}, ctx) is True
    assert rule_applies({"languages_in": ["go", "rust"]}, ctx) is False


def test_languages_in_is_case_insensitive(tmp_path: Path) -> None:
    ctx = _ctx_with_pyproject(tmp_path)
    assert rule_applies({"languages_in": ["Python"]}, ctx) is True
    assert rule_applies({"languages_in": ["PYTHON"]}, ctx) is True


def test_languages_in_non_list_evaluates_false(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    ctx = _ctx_with_pyproject(tmp_path)
    with caplog.at_level(logging.WARNING):
        assert rule_applies({"languages_in": "python"}, ctx) is False
    assert any("languages_in" in r.message for r in caplog.records)


def test_multiple_predicates_are_and(tmp_path: Path) -> None:
    ctx = _ctx_with_pyproject(tmp_path)
    assert rule_applies(
        {"any_language_detected": True, "languages_in": ["python"]}, ctx,
    ) is True
    assert rule_applies(
        {"any_language_detected": True, "languages_in": ["rust"]}, ctx,
    ) is False


def test_unknown_predicate_evaluates_false(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Closed-world: unknown keys block the rule and log a warning.

    This protects against rule packs pinned ahead of the engine
    silently enabling new predicates the engine doesn't yet know.
    """
    ctx = _ctx_with_pyproject(tmp_path)
    with caplog.at_level(logging.WARNING):
        assert rule_applies({"future_predicate_v2": True}, ctx) is False
    assert any("future_predicate_v2" in r.message for r in caplog.records)


# ----------------------------------------------------------------------------
# Loader — parses applies_when off rule YAML
# ----------------------------------------------------------------------------


_RULE_TEMPLATE = textwrap.dedent("""\
    rules_version: 2
    id: test.dummy
    pillar: feedback
    title: Test rule
    weight: 1.0
    severity: warn
    explanation: Test
    match:
      type: path_glob
      require_globs: ["pyproject.toml"]
      forbid_globs: []
    {applies_when}
    """)


def test_loader_carries_applies_when(tmp_path: Path) -> None:
    rule_path = tmp_path / "test_dummy.yaml"
    rule_path.write_text(_RULE_TEMPLATE.format(
        applies_when="applies_when:\n  any_language_detected: true\n",
    ))
    loaded = load_rule_file(rule_path)
    assert loaded is not None
    assert loaded.applies_when == {"any_language_detected": True}


def test_loader_applies_when_absent_is_none(tmp_path: Path) -> None:
    rule_path = tmp_path / "test_dummy.yaml"
    rule_path.write_text(_RULE_TEMPLATE.format(applies_when=""))
    loaded = load_rule_file(rule_path)
    assert loaded is not None
    assert loaded.applies_when is None


def test_loader_rejects_non_mapping_applies_when(tmp_path: Path) -> None:
    from agent_readiness.rules_eval.loader import RuleLoadError

    rule_path = tmp_path / "test_dummy.yaml"
    rule_path.write_text(_RULE_TEMPLATE.format(
        applies_when='applies_when: "not a mapping"\n',
    ))
    with pytest.raises(RuleLoadError, match="applies_when"):
        load_rule_file(rule_path)


# ----------------------------------------------------------------------------
# Evaluator integration — excluded rule produces not_measured + no findings
# ----------------------------------------------------------------------------


def test_evaluator_short_circuits_excluded_rule(tmp_path: Path) -> None:
    """A rule that would otherwise fire is silenced by applies_when.

    The matcher (``path_glob``) would normally produce a finding for
    "AGENTS.md missing", but ``any_language_detected: true`` excludes
    the rule on this YAML-only repo. The result must be ``not_measured``
    with no findings — so the scorer treats it as a non-event.
    """
    (tmp_path / "README.md").write_text("yaml-only repo\n")
    ctx = RepoContext(root=tmp_path)
    assert ctx.detected_languages == []

    rule_path = tmp_path / "rule.yaml"
    rule_path.write_text(textwrap.dedent("""\
        rules_version: 2
        id: needs.agents_md
        pillar: cognitive_load
        title: needs agents md
        weight: 1.0
        severity: warn
        explanation: dummy
        match:
          type: path_glob
          require_globs: ["AGENTS.md"]
          forbid_globs: []
        applies_when:
          any_language_detected: true
        """))
    rule = load_rule_file(rule_path)
    assert rule is not None

    result = evaluate_rule(rule, ctx)
    assert result.not_measured is True
    assert result.findings == []


def test_evaluator_runs_rule_when_applies_when_passes(tmp_path: Path) -> None:
    """Sanity: the same rule fires on a Python repo as expected."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='x'\nversion='0.1.0'\n",
    )
    (tmp_path / "README.md").write_text("python repo\n")
    ctx = RepoContext(root=tmp_path)
    assert "python" in ctx.detected_languages

    rule_path = tmp_path / "rule.yaml"
    rule_path.write_text(textwrap.dedent("""\
        rules_version: 2
        id: needs.agents_md
        pillar: cognitive_load
        title: needs agents md
        weight: 1.0
        severity: warn
        explanation: dummy
        match:
          type: path_glob
          require_globs: ["AGENTS.md"]
          forbid_globs: []
        applies_when:
          any_language_detected: true
        """))
    rule = load_rule_file(rule_path)
    assert rule is not None

    result = evaluate_rule(rule, ctx)
    assert result.not_measured is False
    assert len(result.findings) == 1
    assert result.findings[0].check_id == "needs.agents_md"
