"""Tests for agent_readiness.enumerate.enumerate_workspace.

Coverage:
- single repo (root has .git, no children)
- workspace of two children with .git
- README-only child (qualifies enumeration)
- ignore-list dirs (node_modules, .venv, etc.) are skipped
- 200-child cap fires
- manifest_signals detect pnpm-workspace.yaml, etc.
"""
from __future__ import annotations

from pathlib import Path

from agent_readiness.enumerate import enumerate_workspace
from agent_readiness.models import EnumerationReport


def _make_git(p: Path) -> None:
    (p / ".git").mkdir(parents=True, exist_ok=True)


def _write(p: Path, body: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_single_repo_no_children(tmp_path: Path) -> None:
    _make_git(tmp_path)
    _write(tmp_path / "README.md", "# root")
    result = enumerate_workspace(tmp_path)
    assert isinstance(result, EnumerationReport)
    assert result.root.has_git is True
    assert result.root.has_readme is True
    assert result.children == []
    assert result.stats["children_scanned"] == 0


def test_two_children_with_git(tmp_path: Path) -> None:
    _make_git(tmp_path / "a")
    _write(tmp_path / "a" / "README.md")
    _make_git(tmp_path / "b")
    _write(tmp_path / "b" / "README.md")
    result = enumerate_workspace(tmp_path)
    assert result.root.has_git is False
    assert {c.path.name for c in result.children} == {"a", "b"}
    for c in result.children:
        assert c.has_git is True
        assert c.has_readme is True


def test_readme_only_child_qualifies(tmp_path: Path) -> None:
    _write(tmp_path / "a" / "README.md")
    result = enumerate_workspace(tmp_path)
    assert len(result.children) == 1
    assert result.children[0].path.name == "a"
    assert result.children[0].has_git is False
    assert result.children[0].has_readme is True


def test_ignore_list_dirs_skipped(tmp_path: Path) -> None:
    for d in ("node_modules", ".venv", "dist", "build", "target", "__pycache__"):
        _make_git(tmp_path / d)
        _write(tmp_path / d / "README.md")
    _make_git(tmp_path / "real_child")
    _write(tmp_path / "real_child" / "README.md")
    result = enumerate_workspace(tmp_path)
    assert [c.path.name for c in result.children] == ["real_child"]


def test_no_recursion(tmp_path: Path) -> None:
    """A child's children must not appear in the enumeration."""
    _make_git(tmp_path / "a")
    _write(tmp_path / "a" / "README.md")
    _make_git(tmp_path / "a" / "inner")
    _write(tmp_path / "a" / "inner" / "README.md")
    result = enumerate_workspace(tmp_path)
    assert [c.path.name for c in result.children] == ["a"]


def test_manifest_signal_pnpm_workspace(tmp_path: Path) -> None:
    _make_git(tmp_path)
    _write(tmp_path / "pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n")
    result = enumerate_workspace(tmp_path)
    assert result.manifest_signals["pnpm_workspace"] is True


def test_top_files_capped_at_20(tmp_path: Path) -> None:
    _make_git(tmp_path)
    for i in range(30):
        _write(tmp_path / f"file_{i:02d}.txt")
    result = enumerate_workspace(tmp_path)
    assert len(result.root.top_files) <= 20


def test_scan_truncated_at_200_children(tmp_path: Path) -> None:
    for i in range(205):
        _write(tmp_path / f"c{i:03d}" / "README.md")
    result = enumerate_workspace(tmp_path)
    assert result.stats["scan_truncated"] is True
    assert len(result.children) == 200


def test_path_must_be_directory(tmp_path: Path) -> None:
    f = tmp_path / "not_a_dir.txt"
    f.write_text("hi")
    try:
        enumerate_workspace(f)
    except (NotADirectoryError, ValueError):
        return
    raise AssertionError("expected exception")


def test_language_hint_from_pyproject(tmp_path: Path) -> None:
    _make_git(tmp_path / "child")
    _write(tmp_path / "child" / "pyproject.toml", "[project]\nname = 'x'\n")
    result = enumerate_workspace(tmp_path)
    assert "python" in result.children[0].language_hint
