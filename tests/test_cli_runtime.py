from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = {"PYTHONPATH": str(repo_root / "src"), **__import__("os").environ}
    return subprocess.run(
        [sys.executable, "-m", "agent_readiness.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd or repo_root,
        check=False,
    )


def test_cli_list_object_types(runtime_workspace: Path):
    result = _run_cli(
        "ontology",
        "list-object-types",
        str(runtime_workspace),
        "--json",
        cwd=runtime_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert any(item["name"] == "Repo" for item in payload)


def test_cli_list_object_types_empty(tmp_path: Path):
    result = _run_cli("ontology", "list-object-types", str(tmp_path), "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_cli_query_objects(runtime_workspace: Path):
    result = _run_cli(
        "ontology",
        "query-objects",
        str(runtime_workspace),
        "--object-type",
        "Repo",
        "--where",
        "name=repo-b",
        "--json",
        cwd=runtime_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["id"] == "repo-b"


def test_cli_list_links(runtime_workspace: Path):
    result = _run_cli(
        "ontology",
        "list-links",
        str(runtime_workspace),
        "--from",
        "repo-a",
        "--json",
        cwd=runtime_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["id"] == "a-deps-b"


def test_cli_get_object_found(runtime_workspace: Path):
    result = _run_cli(
        "ontology",
        "get-object",
        str(runtime_workspace),
        "--id",
        "repo-a",
        "--json",
        cwd=runtime_workspace,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["id"] == "repo-a"


def test_cli_get_object_not_found(runtime_workspace: Path):
    result = _run_cli(
        "ontology",
        "get-object",
        str(runtime_workspace),
        "--id",
        "missing",
        "--json",
        cwd=runtime_workspace,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) is None


def test_cli_list_interfaces(runtime_workspace: Path):
    result = _run_cli(
        "ontology",
        "list-interfaces",
        str(runtime_workspace),
        "--json",
        cwd=runtime_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload[0]["name"] == "Versioned"


def test_cli_which_interfaces(runtime_workspace: Path):
    result = _run_cli(
        "ontology",
        "which-interfaces",
        str(runtime_workspace),
        "--object-id",
        "repo-a",
        "--json",
        cwd=runtime_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload[0]["interface"] == "Versioned"


def test_cli_list_functions(runtime_workspace: Path):
    result = _run_cli(
        "ontology",
        "list-functions",
        str(runtime_workspace),
        "--json",
        cwd=runtime_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    by_name = {item["name"]: item for item in payload}
    assert by_name["compute_dep_graph"]["has_implementation"] is True


def test_cli_invoke_function(runtime_workspace: Path):
    result = _run_cli(
        "ontology",
        "invoke-function",
        str(runtime_workspace),
        "--function-name",
        "compute_dep_graph",
        "--json",
        cwd=runtime_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert {"from": "repo-a", "to": "repo-b"} in payload


def test_cli_invoke_function_not_found(runtime_workspace: Path):
    result = _run_cli(
        "ontology",
        "invoke-function",
        str(runtime_workspace),
        "--function-name",
        "missing_impl",
        "--json",
        cwd=runtime_workspace,
    )
    assert result.returncode == 1


def test_cli_ontology_help_lists_runtime_verbs():
    result = _run_cli("ontology", "--help")
    assert result.returncode == 0
    for verb in (
        "list-object-types",
        "query-objects",
        "list-links",
        "get-object",
        "list-interfaces",
        "which-interfaces",
        "list-functions",
        "invoke-function",
    ):
        assert verb in result.stdout
