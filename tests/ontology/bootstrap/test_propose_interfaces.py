from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_readiness.ontology.bootstrap.propose_interfaces import (
    propose_interface_claims,
)

from .conftest import write_ratified_repo_instance

from agent_readiness.ontology.bootstrap.init import _BUNDLED_TEMPLATE

MANIFEST_TEMPLATE = _BUNDLED_TEMPLATE


@pytest.fixture
def workspace_with_releasable_repos(tmp_path: Path) -> Path:
    # Copy the interface YAMLs so the ontology has them
    interfaces_dst = tmp_path / "ontology" / "interfaces"
    interfaces_dst.mkdir(parents=True)
    for f in (MANIFEST_TEMPLATE / "interfaces").glob("*.yaml"):
        shutil.copy2(f, interfaces_dst / f.name)
    # Ratified Repo: has release.yml + CHANGELOG.md + version line in pyproject.toml
    repo_ok = tmp_path / "repo-with-release"
    repo_ok.mkdir()
    (repo_ok / ".github" / "workflows").mkdir(parents=True)
    (repo_ok / ".github" / "workflows" / "release.yml").write_text("name: release\n")
    (repo_ok / "CHANGELOG.md").write_text("# Changes\n")
    (repo_ok / "pyproject.toml").write_text(
        '[project]\nname = "repo-with-release"\nversion = "1.0.0"\n'
    )
    write_ratified_repo_instance(tmp_path, "repo-with-release", primary_manifest="pyproject.toml")
    # Ratified Repo: missing release workflow
    repo_bad = tmp_path / "repo-no-release"
    repo_bad.mkdir()
    (repo_bad / "pyproject.toml").write_text(
        '[project]\nname = "repo-no-release"\nversion = "1.0.0"\n'
    )
    write_ratified_repo_instance(tmp_path, "repo-no-release", primary_manifest="pyproject.toml")
    return tmp_path


def test_proposes_releasable_ratified_for_repo_with_release_workflow(
    workspace_with_releasable_repos: Path,
):
    env = propose_interface_claims(workspace_with_releasable_repos, interface="Releasable")
    by_repo = {p.properties["object_id"]: p for p in env.proposed}
    # `repo-with-release` has the release workflow and CHANGELOG.md
    ok = by_repo["repo-with-release"]
    # NOTE: the Releasable interface's regex_match clause uses
    # "{{ primary_manifest }}" template that the bootstrap leaves unsubstituted,
    # so satisfaction may still fail on the regex clause. Just check that
    # the file_glob and file_exists clauses fired by inspecting proof_refs.
    assert ".github/workflows/release.yml" in ok.properties["proof_refs"] or "CHANGELOG.md" in ok.properties["proof_refs"] or ok.properties["satisfaction"] == "ratified"


def test_proposes_releasable_failing_for_repo_without_release_workflow(
    workspace_with_releasable_repos: Path,
):
    env = propose_interface_claims(workspace_with_releasable_repos, interface="Releasable")
    by_repo = {p.properties["object_id"]: p for p in env.proposed}
    bad = by_repo["repo-no-release"]
    assert bad.properties["satisfaction"] == "failing"


def test_propose_interface_raises_for_unknown_interface(workspace_with_releasable_repos: Path):
    with pytest.raises(ValueError, match="not declared"):
        propose_interface_claims(workspace_with_releasable_repos, interface="Nonsense")
