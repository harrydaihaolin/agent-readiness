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
    with pytest.raises(NotImplementedError, match="not yet supported"):
        propose_object_instances(workspace=dogfood_workspace, object_type="Service")


def test_envelope_skips_non_git_directories(dogfood_workspace: Path):
    env = propose_object_instances(workspace=dogfood_workspace, object_type="Repo")
    ids = {p.id for p in env.proposed}
    assert "not-a-repo" not in ids


@pytest.fixture
def library_workspace(tmp_path: Path) -> Path:
    """Fixture: one repo with a pyproject.toml that declares a distributable lib."""
    repo = tmp_path / "mylib"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "mylib"\nversion = "1.2.3"\n'
    )
    # Also a published npm package in a separate repo
    npm_repo = tmp_path / "mynpmpkg"
    npm_repo.mkdir()
    (npm_repo / ".git").mkdir()
    (npm_repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (npm_repo / "package.json").write_text(
        '{"name": "@org/mynpmpkg", "version": "2.0.0"}\n'
    )
    return tmp_path


def test_proposes_library_from_pyproject(library_workspace: Path):
    env = propose_object_instances(workspace=library_workspace, object_type="Library")
    assert env.target_type == "Library"
    libs = {p.id: p for p in env.proposed}
    assert "mylib" in libs
    assert libs["mylib"].properties["version"] == "1.2.3"
    assert libs["mylib"].properties["registry"] == "pypi"
    assert libs["mylib"].properties["source_repo"] == {"object_type": "Repo", "id": "mylib"}
    assert libs["mylib"].lifecycle.confidence >= 0.9


def test_proposes_library_from_package_json(library_workspace: Path):
    env = propose_object_instances(workspace=library_workspace, object_type="Library")
    libs = {p.id: p for p in env.proposed}
    assert "@org/mynpmpkg" in libs
    assert libs["@org/mynpmpkg"].properties["registry"] == "npm"


@pytest.fixture
def protocol_workspace(tmp_path: Path) -> Path:
    for name in ("foo-protocol", "foo", "bar-with-schema"):
        d = tmp_path / name
        d.mkdir()
        (d / ".git").mkdir()
        (d / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    # bar-with-schema has an inline protocol/schema.json (alternative signal)
    (tmp_path / "bar-with-schema" / "protocol").mkdir()
    (tmp_path / "bar-with-schema" / "protocol" / "schema.json").write_text("{}")
    # foo-protocol gets a version in pyproject.toml so the proposed atom has one
    (tmp_path / "foo-protocol" / "pyproject.toml").write_text(
        '[project]\nname = "foo-protocol"\nversion = "0.5.0"\n'
    )
    return tmp_path


def test_proposes_protocol_for_naming_convention(protocol_workspace: Path):
    env = propose_object_instances(workspace=protocol_workspace, object_type="Protocol")
    ids = {p.id for p in env.proposed}
    assert "foo-protocol" in ids
    assert "bar-with-schema" in ids  # detected via protocol/schema.json
    assert "foo" not in ids  # no naming match, no schema.json


@pytest.fixture
def rulespack_workspace(tmp_path: Path) -> Path:
    """Fixture: repo with rules/*.yaml files that each declare rules_version."""
    repo = tmp_path / "my-rules"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    rules_dir = repo / "rules"
    rules_dir.mkdir()
    (rules_dir / "rule1.yaml").write_text("rules_version: 2\nid: test.x\n")
    (rules_dir / "rule2.yaml").write_text("rules_version: 2\nid: test.y\n")
    # Also create a non-rules-pack repo to make sure detection is selective
    non = tmp_path / "not-a-rulespack"
    non.mkdir()
    (non / ".git").mkdir()
    (non / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    return tmp_path


def test_proposes_rulespack_from_rules_dir(rulespack_workspace: Path):
    env = propose_object_instances(workspace=rulespack_workspace, object_type="RulesPack")
    ids = {p.id for p in env.proposed}
    assert "my-rules" in ids
    assert "not-a-rulespack" not in ids
