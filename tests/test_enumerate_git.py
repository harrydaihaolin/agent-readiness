"""Tests for the git-aware enumerator (plan 2)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _git_init(path: Path) -> None:
    """Minimal `.git` directory — enough for the walker to find it."""
    (path / ".git").mkdir(parents=True, exist_ok=True)


def _make_tree(tmp_path: Path, layout: dict) -> Path:
    """Helper: build a directory tree from a nested dict.

    Keys are directory names; values are either dicts (subdirs) or the
    sentinel string ".git" (creates a .git dir at that level)."""
    def _build(parent: Path, spec: dict) -> None:
        for name, child in spec.items():
            here = parent / name
            here.mkdir(parents=True, exist_ok=True)
            if child == ".git":
                _git_init(here)
            elif isinstance(child, dict):
                _build(here, child)
    _build(tmp_path, layout)
    return tmp_path


@pytest.fixture
def mle_like_workspace(tmp_path: Path) -> Path:
    """Reproduces the user's `mle/` scenario: root has no .git, several
    repos are nested two levels deep under `projects/`."""
    _make_tree(tmp_path, {
        "mle": {
            "notebooks": {},  # no .git, no nesting
            "projects": {
                "llm-eval": ".git",
                "data-pipeline": ".git",
                "feature-store": ".git",
                "web-ui": ".git",
                "inference-svc": ".git",
                "training-svc": ".git",
                "legacy-research": ".git",
            },
            "scratch": {},
        }
    })
    return tmp_path / "mle"


def test_finds_nested_git_repos_at_depth_2(mle_like_workspace: Path):
    """The headline bug. mle/projects/*/.git must be discovered."""
    from agent_readiness.enumerate_git import enumerate_git_repos

    result = enumerate_git_repos(mle_like_workspace)
    assert result.root == str(mle_like_workspace.resolve())
    assert result.root_has_git is False
    found_paths = {r.path for r in result.repos}
    # All 7 projects subdirs with .git must be discovered
    assert "mle/projects/llm-eval" in {os.path.relpath(p, mle_like_workspace.parent) for p in found_paths}
    assert len([r for r in result.repos if r.has_git]) == 7


def test_does_not_recurse_into_found_repos(tmp_path: Path):
    """Once we hit .git, stop walking — submodules / vendored dirs inside
    a repo are out of scope."""
    from agent_readiness.enumerate_git import enumerate_git_repos

    _make_tree(tmp_path, {
        "outer": ".git",
    })
    # Add a fake nested .git BELOW the outer one
    (tmp_path / "outer" / "vendor" / "submodule").mkdir(parents=True)
    (tmp_path / "outer" / "vendor" / "submodule" / ".git").mkdir()
    result = enumerate_git_repos(tmp_path)
    found_paths = [r.path for r in result.repos]
    # Only the outer repo should be found.
    assert any(p.endswith("/outer") for p in found_paths)
    assert not any("submodule" in p for p in found_paths)


def test_prunes_node_modules_and_venv(tmp_path: Path):
    """Standard noise directories must never be walked into, even if they
    contain a `.git` directory (e.g. a vendored sub-repo)."""
    from agent_readiness.enumerate_git import enumerate_git_repos

    (tmp_path / "node_modules" / "some-pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "some-pkg" / ".git").mkdir()
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / ".git").mkdir()
    (tmp_path / "real-repo").mkdir()
    (tmp_path / "real-repo" / ".git").mkdir()
    result = enumerate_git_repos(tmp_path)
    found_paths = [r.path for r in result.repos]
    assert any("real-repo" in p for p in found_paths)
    assert not any("node_modules" in Path(p).parts for p in found_paths)
    assert not any(".venv" in Path(p).parts for p in found_paths)


def test_root_has_git_when_root_is_a_repo(tmp_path: Path):
    from agent_readiness.enumerate_git import enumerate_git_repos

    _git_init(tmp_path)
    result = enumerate_git_repos(tmp_path)
    assert result.root_has_git is True


def test_handles_git_as_file_for_submodules(tmp_path: Path):
    """Submodules and worktrees use `.git` as a FILE pointing to the
    real gitdir. The walker must treat both forms as a repo marker."""
    from agent_readiness.enumerate_git import enumerate_git_repos

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / ".git").write_text("gitdir: ../.git/modules/sub\n")
    result = enumerate_git_repos(tmp_path)
    found_paths = [r.path for r in result.repos]
    assert any(p.endswith("/sub") for p in found_paths)


def test_repos_sorted_by_path_for_determinism(tmp_path: Path):
    """Dashboard rendering depends on stable ordering."""
    from agent_readiness.enumerate_git import enumerate_git_repos

    for name in ("zeta", "alpha", "mu"):
        d = tmp_path / name
        d.mkdir()
        _git_init(d)
    result = enumerate_git_repos(tmp_path)
    names = [r.name for r in result.repos]
    assert names == sorted(names)


def test_returns_directories_walked_and_elapsed_ms(tmp_path: Path):
    from agent_readiness.enumerate_git import enumerate_git_repos

    _make_tree(tmp_path, {
        "a": {"b": {"c": {}, "d": {}}, "e": {}},
    })
    result = enumerate_git_repos(tmp_path)
    assert result.directories_walked > 0
    assert result.elapsed_ms >= 0
