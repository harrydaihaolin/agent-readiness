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


# --- classification_hint (v3.4.3) --------------------------------------
#
# Each rule in the rubric gets a test. The contract the skill follows is
# ``recommended_action`` — we assert that field directly so a future
# rename / refactor of the rule body that breaks the user-visible
# behaviour fails loudly.


def test_classification_hint_envelope_present(tmp_path: Path) -> None:
    """Every enumeration ships a classification_hint (schema 2)."""
    _make_git(tmp_path)
    _write(tmp_path / "README.md")
    result = enumerate_workspace(tmp_path)
    assert result.classification_hint is not None
    assert result.schema == 2
    d = result.to_dict()
    assert "classification_hint" in d
    assert d["classification_hint"]["recommended_action"] in (
        "scan_repo",
        "scan_workspace_async",
        "ask_user",
        "exit",
    )


def test_classification_monorepo_via_manifest(tmp_path: Path) -> None:
    """pnpm-workspace.yaml at root → monorepo, recommend scan_repo."""
    _make_git(tmp_path)
    _write(tmp_path / "pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n")
    h = enumerate_workspace(tmp_path).classification_hint
    assert h is not None
    assert h.classification == "monorepo"
    assert h.confidence == "high"
    assert h.recommended_action == "scan_repo"
    assert "pnpm_workspace" in h.rationale


def test_classification_workspace_of_independents(tmp_path: Path) -> None:
    """Root no .git, ≥ 2 children with .git → dashboard async scan."""
    _make_git(tmp_path / "a")
    _write(tmp_path / "a" / "README.md")
    _make_git(tmp_path / "b")
    _write(tmp_path / "b" / "README.md")
    _make_git(tmp_path / "c")
    _write(tmp_path / "c" / "README.md")
    h = enumerate_workspace(tmp_path).classification_hint
    assert h is not None
    assert h.classification == "workspace_of_independents"
    assert h.confidence == "high"
    assert h.recommended_action == "scan_workspace_async"
    assert "3 children" in h.rationale


def test_classification_single_repo(tmp_path: Path) -> None:
    """Root has .git, no nested .git → single repo, scan_repo."""
    _make_git(tmp_path)
    _write(tmp_path / "README.md")
    _write(tmp_path / "src" / "app.py")
    h = enumerate_workspace(tmp_path).classification_hint
    assert h is not None
    assert h.classification == "single_repo"
    assert h.confidence == "high"
    assert h.recommended_action == "scan_repo"


def test_classification_not_a_code_repo(tmp_path: Path) -> None:
    """No .git, no README, no children → exit."""
    h = enumerate_workspace(tmp_path).classification_hint
    assert h is not None
    assert h.classification == "not_a_code_repo"
    assert h.recommended_action == "exit"


def test_classification_ambiguous_root_and_children_have_git(
    tmp_path: Path,
) -> None:
    """Root .git AND child .git → ambiguous, ask user with three options.

    This is the user-reported dogfood case: signals do not disambiguate
    workspace-with-meta-repo vs. monorepo-with-submodules vs. single
    repo with unrelated checkouts. The skill MUST ask.
    """
    _make_git(tmp_path)
    _write(tmp_path / "README.md")
    _make_git(tmp_path / "child")
    _write(tmp_path / "child" / "README.md")
    h = enumerate_workspace(tmp_path).classification_hint
    assert h is not None
    assert h.classification == "ambiguous"
    assert h.confidence == "ambiguous"
    assert h.recommended_action == "ask_user"
    assert h.ambiguity_reason is not None
    assert h.ambiguity_options is not None
    option_ids = {o["id"] for o in h.ambiguity_options}
    assert option_ids == {"workspace", "monorepo", "single_repo"}
    for opt in h.ambiguity_options:
        assert opt["route"] in ("scan_repo", "scan_workspace_async")
        assert "hint" in opt


def test_classification_ambiguous_one_child_with_git(tmp_path: Path) -> None:
    """Root no .git, exactly 1 child with .git → ask user."""
    _make_git(tmp_path / "only")
    _write(tmp_path / "only" / "README.md")
    h = enumerate_workspace(tmp_path).classification_hint
    assert h is not None
    assert h.classification == "ambiguous"
    assert h.recommended_action == "ask_user"
    assert h.ambiguity_options is not None
    option_ids = {o["id"] for o in h.ambiguity_options}
    assert option_ids == {"workspace", "single_repo"}


def test_classification_ambiguous_no_git_anywhere(tmp_path: Path) -> None:
    """No .git at root or any child, but children exist → ask user (low conf)."""
    _write(tmp_path / "README.md", "# project")
    _write(tmp_path / "child_a" / "README.md")
    _write(tmp_path / "child_b" / "README.md")
    h = enumerate_workspace(tmp_path).classification_hint
    assert h is not None
    assert h.classification == "ambiguous"
    assert h.recommended_action == "ask_user"
    assert h.confidence == "low"
    assert h.ambiguity_options is not None
    option_ids = {o["id"] for o in h.ambiguity_options}
    assert option_ids == {"skip", "single_repo"}


def test_classification_hint_serializes_in_envelope(tmp_path: Path) -> None:
    """The hint round-trips through to_dict so MCP / CLI consumers see it."""
    _make_git(tmp_path / "a")
    _write(tmp_path / "a" / "README.md")
    _make_git(tmp_path / "b")
    _write(tmp_path / "b" / "README.md")
    d = enumerate_workspace(tmp_path).to_dict()
    assert d["schema"] == 2
    hint = d["classification_hint"]
    assert hint["classification"] == "workspace_of_independents"
    assert hint["recommended_action"] == "scan_workspace_async"
    # ambiguity_reason / ambiguity_options are absent for non-ask cases
    assert "ambiguity_reason" not in hint
    assert "ambiguity_options" not in hint
