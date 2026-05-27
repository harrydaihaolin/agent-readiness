"""Engine-layer tests: REGISTRY, run_inference, DerivedViolation shape.

These tests don't exercise any specific evaluator beyond using one
of the registered rules to confirm round-trip behaviour. Per-rule
behaviour lives in ``test_evaluators.py``.
"""

from __future__ import annotations

import pytest

from agent_readiness.ontology.reasoning import (
    REGISTRY,
    DerivedViolation,
    run_inference,
    violation_to_dict,
)

from .conftest import make_link, make_ontology


def test_all_six_v1_rules_registered() -> None:
    """The v1 rule set (from the Bundle C plan) must all be present.

    If a rule is dropped from this list it should be a deliberate
    design decision documented in a follow-up plan, not a silent
    regression. New rules added beyond v1 are allowed.
    """
    expected = {
        "ontology.inference.acyclic_dependsOn",
        "ontology.inference.consumer_must_pin_protocol_version",
        "ontology.inference.coupled_consumers_must_agree_on_major",
        "ontology.inference.irreflexive_dependsOn",
        "ontology.inference.protocol_provider_must_be_releasable",
        "ontology.inference.provider_must_be_documented",
    }
    assert expected.issubset(set(REGISTRY.evaluators))


def test_run_inference_empty_ontology_returns_empty() -> None:
    """An empty ontology has nothing to derive — every evaluator
    must short-circuit cleanly, not crash."""
    ont = make_ontology()
    assert run_inference(ont) == []


def test_rule_filter_selects_one_evaluator() -> None:
    """``rule_filter`` runs only the named evaluator; an unknown id
    returns an empty list rather than raising."""
    ont = make_ontology(
        links=[make_link("dependsOn", "a", "a")]
    )
    only_reflexive = run_inference(
        ont, rule_filter="ontology.inference.irreflexive_dependsOn"
    )
    assert len(only_reflexive) == 1
    assert only_reflexive[0].rule_id == "ontology.inference.irreflexive_dependsOn"

    other = run_inference(
        ont, rule_filter="ontology.inference.acyclic_dependsOn"
    )
    assert other == []  # self-loop reported by *irreflexive*, not cycle rule

    unknown = run_inference(ont, rule_filter="ontology.inference.bogus")
    assert unknown == []


def test_violation_to_dict_drops_none_subject_id() -> None:
    v = DerivedViolation(rule_id="x", detail="y")
    d = violation_to_dict(v)
    assert "subject_id" not in d
    assert d == {"rule_id": "x", "detail": "y", "severity": "warn"}


def test_register_rejects_duplicates() -> None:
    """Re-registering the same rule_id must raise so duplicate
    evaluators surface at import time, not as silently-shadowed
    behaviour."""
    from agent_readiness.ontology.reasoning.engine import register

    @register("ontology.inference._test_only_dup_check")
    def _evaluate_once(_ont):  # noqa: ARG001
        return []

    with pytest.raises(ValueError, match="already registered"):
        @register("ontology.inference._test_only_dup_check")
        def _evaluate_twice(_ont):  # noqa: ARG001
            return []

    REGISTRY.evaluators.pop("ontology.inference._test_only_dup_check", None)
