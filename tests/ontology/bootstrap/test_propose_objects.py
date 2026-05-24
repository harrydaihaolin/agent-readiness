from __future__ import annotations

from pathlib import Path

import pytest

from agent_readiness.ontology.bootstrap.propose_objects import propose_object_instances


@pytest.fixture
def dogfood_workspace(tmp_path: Path) -> Path:
    """Build a 3-repo workspace stub on the fly.

    repo-a:  pyproject.toml only (unambiguous python)
    repo-b:  package.json only (unambiguous typescript)
    repo-c-ambiguous:  both pyproject.toml and package.json
    not-a-repo:  no .git, should be ignored
    """
    for name in ("repo-a", "repo-b", "repo-c-ambiguous"):
        (tmp_path / name).mkdir()
        (tmp_path / name / ".git").mkdir()
        (tmp_path / name / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (tmp_path / name / "README.md").write_text("# " + name + "\n")
    (tmp_path / "repo-a" / "pyproject.toml").write_text(
        '[project]\nname = "repo-a"\nversion = "0.1.0"\n'
    )
    (tmp_path / "repo-b" / "package.json").write_text(
        '{"name": "repo-b", "version": "0.2.0"}\n'
    )
    (tmp_path / "repo-c-ambiguous" / "pyproject.toml").write_text(
        '[project]\nname = "repo-c-ambiguous"\nversion = "0.3.0"\n'
    )
    (tmp_path / "repo-c-ambiguous" / "package.json").write_text(
        '{"name": "repo-c-ambiguous", "version": "0.3.0"}\n'
    )
    # not-a-repo: no .git
    (tmp_path / "not-a-repo").mkdir()
    (tmp_path / "not-a-repo" / "README.md").write_text("nope")
    return tmp_path


def test_proposes_repo_per_subdir_with_dotgit(dogfood_workspace: Path):
    env = propose_object_instances(workspace=dogfood_workspace, object_type="Repo")
    ids = {p.id for p in env.proposed}
    assert ids == {"repo-a", "repo-b", "repo-c-ambiguous"}
    assert env.tool == "bootstrap.propose_object_instances"
    assert env.target_type == "Repo"


def test_high_confidence_for_unambiguous_repo(dogfood_workspace: Path):
    env = propose_object_instances(workspace=dogfood_workspace, object_type="Repo")
    repo_a = next(p for p in env.proposed if p.id == "repo-a")
    assert repo_a.lifecycle.confidence >= 0.9
    assert repo_a.lifecycle.markers == []
    assert repo_a.properties["primary_manifest"] == "pyproject.toml"
    assert "python" in repo_a.properties["languages"]


def test_low_confidence_with_markers_for_ambiguous(dogfood_workspace: Path):
    env = propose_object_instances(workspace=dogfood_workspace, object_type="Repo")
    repo_c = next(p for p in env.proposed if p.id == "repo-c-ambiguous")
    assert repo_c.lifecycle.confidence < 0.6
    assert "spec.properties.primary_manifest" in repo_c.lifecycle.markers
    assert len(env.ambiguities) >= 1
    assert any(a.id == "repo-c-ambiguous" for a in env.ambiguities)


def test_no_manifest_low_confidence_and_marker(dogfood_workspace: Path):
    # Add a fourth repo with no recognized manifest
    repo_d = dogfood_workspace / "repo-d-nomanifest"
    repo_d.mkdir()
    (repo_d / ".git").mkdir()
    (repo_d / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    env = propose_object_instances(workspace=dogfood_workspace, object_type="Repo")
    repo_d_prop = next(p for p in env.proposed if p.id == "repo-d-nomanifest")
    assert repo_d_prop.lifecycle.confidence < 0.5
    assert "spec.properties.primary_manifest" in repo_d_prop.lifecycle.markers


def test_unsupported_object_type_raises(dogfood_workspace: Path):
    with pytest.raises(NotImplementedError, match="M1.4"):
        propose_object_instances(workspace=dogfood_workspace, object_type="Library")


def test_envelope_skips_non_git_directories(dogfood_workspace: Path):
    env = propose_object_instances(workspace=dogfood_workspace, object_type="Repo")
    ids = {p.id for p in env.proposed}
    assert "not-a-repo" not in ids
