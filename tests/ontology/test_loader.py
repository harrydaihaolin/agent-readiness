from __future__ import annotations

from pathlib import Path

import pytest

from agent_readiness.ontology.loader import Ontology, load_ontology
from agent_readiness_insights_protocol.ontology.types import ObjectType

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
