from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from agent_readiness.ontology.loader import Ontology, get_id_template, load_ontology
from agent_readiness_insights_protocol.ontology.types import ObjectType


def _object_type_with(identity: dict) -> ObjectType:
    return ObjectType.model_validate({
        "apiVersion": "agent-readiness.io/v1",
        "kind": "ObjectType",
        "metadata": {"name": "X"},
        "spec": {"identity": identity, "properties": []},
    })


def test_get_id_template_prefers_id_template():
    ot = _object_type_with({"id_template": "{{ name }}"})
    assert get_id_template(ot) == "{{ name }}"


def test_get_id_template_falls_back_to_pk_expression_with_warning():
    ot = _object_type_with({"pk_expression": "{{ name }}"})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert get_id_template(ot) == "{{ name }}"
    assert any("pk_expression" in str(w.message) for w in caught)


def test_get_id_template_returns_none_when_neither_set():
    ot = _object_type_with({})
    assert get_id_template(ot) is None

FIXTURE = Path(__file__).parent.parent / "fixtures" / "ontology_minimal"


def test_load_ontology_returns_typed_value():
    ont = load_ontology(FIXTURE / "ontology")
    assert isinstance(ont, Ontology)
    assert "Repo" in ont.object_types
    assert isinstance(ont.object_types["Repo"], ObjectType)


def test_load_ontology_missing_dir_returns_empty():
    ont = load_ontology(FIXTURE / "ontology_does_not_exist")
    assert ont.object_types == {}
    assert ont.link_types == {}
    assert ont.interfaces == {}


def test_load_ontology_rejects_invalid_yaml(tmp_path):
    bad_root = tmp_path / "ontology"
    bad_dir = bad_root / "objectTypes"
    bad_dir.mkdir(parents=True)
    bad_file = bad_dir / "Bad.yaml"
    bad_file.write_text(
        "apiVersion: wrong\nkind: ObjectType\nmetadata:\n  name: Bad\nspec: {}\n"
    )
    with pytest.raises(ValueError, match="apiVersion"):
        load_ontology(bad_root)
