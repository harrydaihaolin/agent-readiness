from __future__ import annotations

from pathlib import Path

import pytest

from agent_readiness.ontology.bootstrap.propose_functions import (
    propose_function_implementations,
)


def test_propose_compute_publish_order_writes_stub(tmp_path: Path):
    env = propose_function_implementations(tmp_path, function_type="compute_publish_order")
    written = tmp_path / "ontology" / "functions" / "compute_publish_order.py"
    assert written.is_file()
    src = written.read_text()
    assert "def compute_publish_order(" in src
    assert len(env.proposed) == 1
    assert env.proposed[0].id == "compute_publish_order"


def test_propose_compute_change_impact_and_dep_graph_write_stubs(tmp_path: Path):
    propose_function_implementations(tmp_path, function_type="compute_change_impact")
    propose_function_implementations(tmp_path, function_type="compute_dep_graph")
    assert (tmp_path / "ontology" / "functions" / "compute_change_impact.py").is_file()
    assert (tmp_path / "ontology" / "functions" / "compute_dep_graph.py").is_file()


def test_unknown_function_raises(tmp_path: Path):
    with pytest.raises(NotImplementedError, match="Unknown function_type"):
        propose_function_implementations(tmp_path, function_type="bogus")
