from __future__ import annotations

import pytest

from agent_readiness.ontology.identity import compute_pk


def test_compute_pk_single_variable():
    assert compute_pk("{{ name }}", {"name": "foo"}) == "foo"


def test_compute_pk_multiple_variables():
    assert (
        compute_pk("{{ name }}@{{ version }}", {"name": "foo", "version": "1.2.3"})
        == "foo@1.2.3"
    )


def test_compute_pk_strips_inner_whitespace():
    assert compute_pk("{{name}}#{{ path }}", {"name": "foo", "path": "bar"}) == "foo#bar"


def test_compute_pk_coerces_non_strings():
    assert compute_pk("{{ v }}", {"v": 7}) == "7"


def test_compute_pk_missing_property_raises():
    with pytest.raises(KeyError, match="version"):
        compute_pk("{{ name }}@{{ version }}", {"name": "foo"})


def test_compute_pk_literal_template_unchanged():
    assert compute_pk("static-id", {}) == "static-id"
