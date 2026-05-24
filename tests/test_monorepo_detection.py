"""Tests for monorepo signal detection.

Two surfaces feed the "is this a monorepo?" question and they must
agree: :py:attr:`RepoContext.monorepo_tools` (per-repo scan path) and
:py:func:`enumerate._detect_manifest_signals` (workspace-scan
fast-path). The convention-monorepo heuristic is the one that catches
enterprise Python monorepos that pre-date ``uv`` / ``rye`` workspace
declarations.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from agent_readiness.context import RepoContext
from agent_readiness.enumerate import enumerate_workspace


def _write(p: Path, content: str = "") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


# ----------------------------------------------------------------------------
# convention-monorepo: the killer FP fix
# ----------------------------------------------------------------------------


def test_convention_monorepo_fires_on_sibling_pyprojects(tmp_path: Path) -> None:
    """N sibling packages each with their own pyproject.toml → monorepo.

    Mirrors the shape of `mle/thing` and other enterprise Python
    monorepos: a thin ruff-only root `pyproject.toml`, then N sibling
    package directories each carrying their own manifest.
    """
    _write(tmp_path / "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
    for pkg in ("cis", "cmr", "mds", "hcm"):
        _write(tmp_path / pkg / "pyproject.toml", '[tool.ruff]\nextend = "../pyproject.toml"\n')
        _write(tmp_path / pkg / "__init__.py", "")

    ctx = RepoContext(root=tmp_path)
    assert "convention-monorepo" in ctx.monorepo_tools
    assert ctx.is_monorepo is True

    report = enumerate_workspace(tmp_path)
    assert report.manifest_signals["convention_monorepo"] is True


def test_convention_monorepo_handles_mixed_ecosystems(tmp_path: Path) -> None:
    """A Python + JS + Go sibling layout still counts as a monorepo."""
    _write(tmp_path / "py_pkg" / "pyproject.toml", "")
    _write(tmp_path / "js_pkg" / "package.json", "{}")
    _write(tmp_path / "go_pkg" / "go.mod", "module example.com/go_pkg\n")

    ctx = RepoContext(root=tmp_path)
    assert "convention-monorepo" in ctx.monorepo_tools


def test_convention_monorepo_skips_below_threshold(tmp_path: Path) -> None:
    """A single nested package next to the real root is NOT a monorepo.

    A ``examples/foo/setup.py`` next to a normal Python project doesn't
    count — that's the bar that keeps false positives down.
    """
    _write(tmp_path / "pyproject.toml", "[project]\nname='real-pkg'\nversion='0.1.0'\n")
    _write(tmp_path / "examples" / "foo" / "setup.py", "from setuptools import setup; setup()")

    ctx = RepoContext(root=tmp_path)
    assert "convention-monorepo" not in ctx.monorepo_tools
    assert ctx.is_monorepo is False


def test_convention_monorepo_ignores_excluded_dirs(tmp_path: Path) -> None:
    """node_modules / .venv / dist children must not inflate the count."""
    _write(tmp_path / "pyproject.toml", "")
    _write(tmp_path / "node_modules" / "lodash" / "package.json", "{}")
    _write(tmp_path / ".venv" / "pyvenv.cfg", "")
    _write(tmp_path / "dist" / "wheel-build" / "setup.py", "")
    _write(tmp_path / "real_pkg" / "pyproject.toml", "")
    # Only 1 sibling manifest qualifies (real_pkg) → no convention-monorepo.

    ctx = RepoContext(root=tmp_path)
    assert "convention-monorepo" not in ctx.monorepo_tools


def test_convention_monorepo_depth_one_only(tmp_path: Path) -> None:
    """Nested grandchildren must not bypass the depth-1 limit."""
    _write(tmp_path / "pyproject.toml", "")
    _write(tmp_path / "services" / "api" / "pyproject.toml", "")
    _write(tmp_path / "services" / "worker" / "pyproject.toml", "")
    # 2 grandchildren with manifests, but only 1 direct child (services) ─
    # not enough on its own to trip the heuristic.

    ctx = RepoContext(root=tmp_path)
    # `services/` directly has no manifest, so it doesn't count even
    # though its subtree has two. is_monorepo stays False.
    assert "convention-monorepo" not in ctx.monorepo_tools


# ----------------------------------------------------------------------------
# Explicit workspace declarations
# ----------------------------------------------------------------------------


def test_uv_workspace_is_detected(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", textwrap.dedent("""\
        [project]
        name = "umbrella"
        version = "0.1.0"

        [tool.uv.workspace]
        members = ["packages/*"]
    """))

    ctx = RepoContext(root=tmp_path)
    assert "uv-workspace" in ctx.monorepo_tools
    assert ctx.is_monorepo is True


def test_rye_workspace_is_detected(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", textwrap.dedent("""\
        [project]
        name = "umbrella"
        version = "0.1.0"

        [tool.rye.workspace]
        members = ["packages/*"]
    """))

    ctx = RepoContext(root=tmp_path)
    assert "rye-workspace" in ctx.monorepo_tools


def test_cargo_workspace_is_detected(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", textwrap.dedent("""\
        [workspace]
        members = ["crates/*"]
    """))

    ctx = RepoContext(root=tmp_path)
    assert "cargo-workspace" in ctx.monorepo_tools


def test_gradle_multi_project_is_detected_kts(tmp_path: Path) -> None:
    _write(tmp_path / "settings.gradle.kts", 'include(":app", ":lib")\n')

    ctx = RepoContext(root=tmp_path)
    assert "gradle-multi-project" in ctx.monorepo_tools


def test_gradle_multi_project_is_detected_groovy(tmp_path: Path) -> None:
    _write(tmp_path / "settings.gradle", "include 'app', 'lib'\n")

    ctx = RepoContext(root=tmp_path)
    assert "gradle-multi-project" in ctx.monorepo_tools


# ----------------------------------------------------------------------------
# JS ecosystem (regression coverage for previously existing detection)
# ----------------------------------------------------------------------------


def test_npm_workspaces_still_detected(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"name": "root", "workspaces": ["packages/*"]}')

    ctx = RepoContext(root=tmp_path)
    assert "npm-workspaces" in ctx.monorepo_tools


def test_turbo_still_detected(tmp_path: Path) -> None:
    _write(tmp_path / "turbo.json", '{"pipeline": {}}')

    ctx = RepoContext(root=tmp_path)
    assert "turborepo" in ctx.monorepo_tools


# ----------------------------------------------------------------------------
# Plain single repo: nothing should fire
# ----------------------------------------------------------------------------


def test_plain_single_python_repo_is_not_monorepo(tmp_path: Path) -> None:
    """A single-package Python repo is not a monorepo by any signal."""
    _write(tmp_path / "pyproject.toml", "[project]\nname='x'\nversion='0.1.0'\n")
    _write(tmp_path / "src" / "x" / "__init__.py", "")
    _write(tmp_path / "tests" / "test_x.py", "def test_ok(): pass\n")

    ctx = RepoContext(root=tmp_path)
    assert ctx.monorepo_tools == []
    assert ctx.is_monorepo is False
