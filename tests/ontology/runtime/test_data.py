from __future__ import annotations

from pathlib import Path

from agent_readiness.ontology.runtime import (
    get_object,
    list_interfaces,
    list_links,
    list_object_types,
    query_objects,
    which_interfaces,
)


def test_list_object_types(runtime_workspace: Path):
    types = list_object_types(runtime_workspace)
    assert len(types) == 1
    assert types[0]["name"] == "Repo"
    assert types[0]["description"] == "A git repository participating in the workspace."
    assert types[0]["properties_schema"]


def test_list_object_types_empty_workspace(tmp_path: Path):
    assert list_object_types(tmp_path) == []


def test_query_objects_all(runtime_workspace: Path):
    repos = query_objects(runtime_workspace, "Repo")
    assert len(repos) == 3
    assert {r["id"] for r in repos} == {"repo-a", "repo-b", "repo-c"}


def test_query_objects_where_filter(runtime_workspace: Path):
    repos = query_objects(runtime_workspace, "Repo", where={"name": "repo-b"})
    assert len(repos) == 1
    assert repos[0]["id"] == "repo-b"


def test_query_objects_unknown_type(runtime_workspace: Path):
    assert query_objects(runtime_workspace, "Nonsense") == []


def test_list_links_all(runtime_workspace: Path):
    links = list_links(runtime_workspace)
    assert len(links) == 2
    assert {link["id"] for link in links} == {"a-deps-b", "b-deps-c"}


def test_list_links_filter_from(runtime_workspace: Path):
    links = list_links(runtime_workspace, from_id="repo-a")
    assert len(links) == 1
    assert links[0]["to"]["id"] == "repo-b"


def test_list_links_empty_workspace(tmp_path: Path):
    assert list_links(tmp_path) == []


def test_get_object_found(runtime_workspace: Path):
    obj = get_object(runtime_workspace, "repo-a")
    assert obj is not None
    assert obj["id"] == "repo-a"
    assert obj["type"] == "Repo"


def test_get_object_not_found(runtime_workspace: Path):
    assert get_object(runtime_workspace, "missing") is None


def test_list_interfaces(runtime_workspace: Path):
    ifaces = list_interfaces(runtime_workspace)
    assert len(ifaces) == 1
    assert ifaces[0]["name"] == "Versioned"
    assert ifaces[0]["satisfaction_proof"]["type"] == "regex_match"


def test_list_interfaces_empty_workspace(tmp_path: Path):
    assert list_interfaces(tmp_path) == []


def test_which_interfaces(runtime_workspace: Path):
    claims = which_interfaces(runtime_workspace, "repo-a")
    assert len(claims) == 1
    assert claims[0]["interface"] == "Versioned"
    assert claims[0]["satisfaction"] == "ratified"
    assert claims[0]["proof_refs"] == ["pyproject.toml"]


def test_which_interfaces_missing_object(runtime_workspace: Path):
    assert which_interfaces(runtime_workspace, "missing") == []
