from __future__ import annotations

from pathlib import Path

import pytest

from agent_readiness.ontology.runtime import (
    FunctionInvocationError,
    FunctionNotFoundError,
    invoke_function,
    list_functions,
)


def test_list_functions_reports_has_implementation(runtime_workspace: Path):
    fns = list_functions(runtime_workspace)
    by_name = {fn["name"]: fn for fn in fns}
    assert by_name["compute_dep_graph"]["has_implementation"] is True
    assert by_name["missing_impl"]["has_implementation"] is False
    assert by_name["compute_dep_graph"]["signature"]["params"] == []
    assert by_name["compute_dep_graph"]["signature"]["returns"]


def test_invoke_function_round_trip(runtime_workspace: Path):
    edges = invoke_function(runtime_workspace, "compute_dep_graph")
    assert edges == [
        {"from": "repo-a", "to": "repo-b"},
        {"from": "repo-b", "to": "repo-c"},
    ]


def test_invoke_function_not_found(runtime_workspace: Path):
    with pytest.raises(FunctionNotFoundError, match="missing_impl"):
        invoke_function(runtime_workspace, "missing_impl")


def test_invoke_function_propagates_error(runtime_workspace: Path):
    funcs = runtime_workspace / "ontology" / "functions"
    funcs.mkdir(parents=True, exist_ok=True)
    (funcs / "boom.py").write_text("def boom(ontology_root, **kw):\n    raise ValueError('kaboom')\n")
    (funcs / "boom.yaml").write_text(
        "apiVersion: agent-readiness.io/v1\nkind: FunctionType\nmetadata:\n  name: boom\nspec:\n  inputs: []\n  outputs: []\n"
    )
    with pytest.raises(FunctionInvocationError) as exc_info:
        invoke_function(runtime_workspace, "boom")
    assert isinstance(exc_info.value.cause, ValueError)
    assert str(exc_info.value.cause) == "kaboom"
