"""Tests for ``agent_readiness.workspace_detect``.

The detector is heuristic-heavy and exposes a wire format that the MCP
server, the skill, and any edge client all depend on. Every change here
should keep the wire format stable (``detect_v1``) or bump it.

The fixtures are built on-the-fly in ``tmp_path`` so the test suite
doesn't need to vendor a parallel set of fixture trees alongside
``tests/fixtures/`` (which the engine's other tests use). The four
synthetic monorepos / multi-repo-workspaces described in the design
spec live in the ``agent-readiness-fixtures`` repo and are exercised
by the rules-pack snapshot tests, not here.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_readiness.workspace_detect import (
    DETECT_VERSION,
    detect,
)


# ---------- helpers -----------------------------------------------------


def _make_git(repo_root: Path) -> None:
    """Mark ``repo_root`` as a git repo (cheaply, no real history)."""
    (repo_root / ".git").mkdir(parents=True, exist_ok=True)


def _write(p: Path, body: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ---------- step 1: root is a repo -------------------------------------


class TestStep1SingleRepo:
    """Root has .git but no monorepo signal — classify as single_repo."""

    def test_bare_single_repo(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(tmp_path / "README.md", "# bare")
        result = detect(tmp_path)
        assert result.classification == "single_repo"
        assert result.confidence == "high"
        assert result.version == DETECT_VERSION
        assert len(result.repos) == 1
        assert result.repos[0].has_git is True
        assert result.repos[0].rel_path == "./"
        assert result.signals["fired"] == []

    def test_library_with_examples_dir_not_a_monorepo(self, tmp_path: Path) -> None:
        """Examples/ is in the prune list — manifests inside don't count."""
        _make_git(tmp_path)
        _write(tmp_path / "pyproject.toml", "[project]\nname='lib'\n")
        # Three nested manifests but all under examples/ — must not trip Signal C.
        for i in range(3):
            _write(tmp_path / "examples" / f"demo{i}" / "package.json", "{}")
        result = detect(tmp_path)
        assert result.classification == "single_repo", result.signals
        assert result.confidence == "high"


class TestStep1Monorepo:
    """Each Signal A/B/C produces a monorepo classification at the right confidence."""

    @pytest.mark.parametrize(
        ("filename", "body", "label_contains"),
        [
            ("pnpm-workspace.yaml", "packages:\n  - 'packages/*'\n", "pnpm-workspace.yaml"),
            ("nx.json", "{}", "nx.json"),
            ("turbo.json", "{}", "turbo.json"),
            ("lerna.json", "{}", "lerna.json"),
            ("rush.json", "{}", "rush.json"),
            ("go.work", "use ./a\nuse ./b\n", "go.work"),
            ("WORKSPACE", "", "WORKSPACE"),
            ("WORKSPACE.bazel", "", "WORKSPACE.bazel"),
            ("MODULE.bazel", "", "MODULE.bazel"),
            ("pants.toml", "", "pants.toml"),
            (".buckconfig", "", ".buckconfig"),
        ],
    )
    def test_signal_a_file_existence(
        self, tmp_path: Path, filename: str, body: str, label_contains: str
    ) -> None:
        _make_git(tmp_path)
        _write(tmp_path / filename, body)
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert result.confidence == "high"
        assert any(label_contains in lbl for lbl in result.signals["fired"])

    def test_signal_a_package_json_workspaces(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(tmp_path / "package.json", '{"name":"r","workspaces":["packages/*"]}')
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert result.confidence == "high"
        assert "A:package.json#workspaces" in result.signals["fired"]

    def test_signal_a_cargo_workspace(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(
            tmp_path / "Cargo.toml",
            "[workspace]\nmembers = ['crates/*']\n",
        )
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert result.confidence == "high"
        assert "A:Cargo.toml#workspace" in result.signals["fired"]

    def test_signal_a_cargo_plain_library_does_not_fire(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(tmp_path / "Cargo.toml", "[package]\nname = 'libfoo'\n")
        result = detect(tmp_path)
        assert result.classification == "single_repo"

    @pytest.mark.parametrize(
        "section",
        ["[tool.uv.workspace]", "[tool.rye.workspace]"],
    )
    def test_signal_a_pyproject_workspace(self, tmp_path: Path, section: str) -> None:
        _make_git(tmp_path)
        _write(tmp_path / "pyproject.toml", f"{section}\nmembers = ['packages/*']\n")
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert result.confidence == "high"

    def test_signal_a_poetry_packages(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(
            tmp_path / "pyproject.toml",
            "[tool.poetry]\nname = 'r'\npackages = [\n  { include = 'a' },\n]\n",
        )
        result = detect(tmp_path)
        assert result.classification == "monorepo"

    def test_signal_a_plain_pyproject_does_not_fire(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(tmp_path / "pyproject.toml", "[project]\nname = 'r'\n")
        result = detect(tmp_path)
        assert result.classification == "single_repo"

    def test_signal_a_gradle_settings_with_include(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(
            tmp_path / "settings.gradle",
            "rootProject.name = 'r'\ninclude ':app', ':lib'\n",
        )
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert "A:settings.gradle#include" in result.signals["fired"]

    def test_signal_a_maven_modules(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(
            tmp_path / "pom.xml",
            "<project><modules><module>m1</module></modules></project>",
        )
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert "A:pom.xml#modules" in result.signals["fired"]

    def test_signal_a_mix_umbrella(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(
            tmp_path / "mix.exs",
            "defmodule R.MixProject do\n  def project, do: [apps_path: \"apps\"]\nend\n",
        )
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert "A:mix.exs#apps_path" in result.signals["fired"]

    def test_signal_b_convention_dir(self, tmp_path: Path) -> None:
        """`apps/` with >=2 child manifests fires Signal B at medium confidence."""
        _make_git(tmp_path)
        _write(tmp_path / "apps" / "foo" / "package.json", "{}")
        _write(tmp_path / "apps" / "bar" / "package.json", "{}")
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert result.confidence == "medium"
        assert any(lbl.startswith("B:apps") for lbl in result.signals["fired"])

    def test_signal_b_packages_dir(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(tmp_path / "packages" / "a" / "package.json", "{}")
        _write(tmp_path / "packages" / "b" / "package.json", "{}")
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert result.confidence == "medium"

    def test_signal_b_single_child_not_enough(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(tmp_path / "apps" / "only" / "package.json", "{}")
        result = detect(tmp_path)
        assert result.classification == "single_repo"

    def test_signal_c_manifest_density(self, tmp_path: Path) -> None:
        """Three scattered manifests with no convention dir → Signal C (low)."""
        _make_git(tmp_path)
        _write(tmp_path / "tools" / "package.json", "{}")
        _write(tmp_path / "docs-site" / "package.json", "{}")
        _write(tmp_path / "scripts-runner" / "pyproject.toml", "[project]\nname='s'\n")
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert result.confidence == "low"
        assert "C:manifest_density" in result.signals["fired"]

    def test_signal_a_takes_precedence_over_b_and_c(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        _write(tmp_path / "pnpm-workspace.yaml", "packages: ['packages/*']")
        _write(tmp_path / "apps" / "foo" / "package.json", "{}")
        _write(tmp_path / "apps" / "bar" / "package.json", "{}")
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        # A fired → high regardless of whether B also fires.
        assert result.confidence == "high"


# ---------- step 2: parent dir with N child .git/ ----------------------


class TestStep2MultiRepo:
    """No root .git, but children have .git → multi_repo_workspace."""

    def test_two_child_repos(self, tmp_path: Path) -> None:
        for name in ("alpha", "beta"):
            _make_git(tmp_path / name)
            _write(tmp_path / name / "README.md", f"# {name}")
        result = detect(tmp_path)
        assert result.classification == "multi_repo_workspace"
        assert result.confidence == "high"
        names = sorted(r.name for r in result.repos)
        assert names == ["alpha", "beta"]
        assert all(r.has_git for r in result.repos)
        assert all(r.rel_path.startswith("./") for r in result.repos)

    def test_one_child_repo_returns_that_child(self, tmp_path: Path) -> None:
        _make_git(tmp_path / "only")
        result = detect(tmp_path)
        assert result.classification == "single_repo"
        assert result.confidence == "high"
        assert len(result.repos) == 1
        assert result.repos[0].name == "only"
        assert "single_child_repo" in result.signals["fired"][0]

    def test_dot_dirs_are_skipped(self, tmp_path: Path) -> None:
        _make_git(tmp_path / "real")
        _make_git(tmp_path / ".cache")
        result = detect(tmp_path)
        assert result.classification == "single_repo"
        assert result.repos[0].name == "real"

    def test_node_modules_pruned(self, tmp_path: Path) -> None:
        _make_git(tmp_path / "real")
        _make_git(tmp_path / "node_modules")  # adversarial
        result = detect(tmp_path)
        assert result.classification == "single_repo"
        assert result.repos[0].name == "real"

    def test_git_file_pointer(self, tmp_path: Path) -> None:
        """`.git` is a file (worktree / submodule) — still counts as a repo."""
        repo = tmp_path / "worktree-repo"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: /elsewhere/.git/worktrees/foo\n", encoding="utf-8")
        other = tmp_path / "normal-repo"
        _make_git(other)
        result = detect(tmp_path)
        assert result.classification == "multi_repo_workspace"
        names = sorted(r.name for r in result.repos)
        assert names == ["normal-repo", "worktree-repo"]


# ---------- step 3: no .git anywhere -----------------------------------


class TestStep3NoGitFallback:
    def test_two_children_with_manifests_only(self, tmp_path: Path) -> None:
        _write(tmp_path / "alpha" / "pyproject.toml", "[project]\nname='alpha'\n")
        _write(tmp_path / "beta" / "pyproject.toml", "[project]\nname='beta'\n")
        result = detect(tmp_path)
        assert result.classification == "multi_repo_workspace"
        assert result.confidence == "medium"
        assert all(r.has_git is False for r in result.repos)

    def test_signal_a_without_git(self, tmp_path: Path) -> None:
        """Tarball-unzipped pnpm workspace (no .git/) still classifies as monorepo.

        Spec: "Step 3 — same logic as steps 1+2 but using manifests
        instead of .git entries." Without this, a user who downloaded
        a workspace as a zip would get `multi_repo_workspace` for what
        is really one repo with internal workspaces.
        """
        _write(tmp_path / "pnpm-workspace.yaml", "packages:\n  - 'packages/*'\n")
        _write(tmp_path / "package.json", '{"name":"r"}')
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert result.confidence == "high"
        assert any("pnpm-workspace.yaml" in lbl for lbl in result.signals["fired"])

    def test_signal_b_without_git(self, tmp_path: Path) -> None:
        _write(tmp_path / "apps" / "foo" / "package.json", "{}")
        _write(tmp_path / "apps" / "bar" / "package.json", "{}")
        result = detect(tmp_path)
        assert result.classification == "monorepo"
        assert result.confidence == "medium"

    def test_completely_empty_dir(self, tmp_path: Path) -> None:
        result = detect(tmp_path)
        assert result.classification == "single_repo"
        assert result.confidence == "low"


# ---------- AGENTS.md enrichment --------------------------------------


class TestAgentsMdEnrichment:
    """The detector pulls display_name + description from a root AGENTS.md table.

    AGENTS.md is enrichment, not source of truth: missing rows or
    misclassified ones never change the heuristic classification, only
    the per-repo metadata + drift warnings.
    """

    def _make_workspace_with_agents(
        self,
        tmp_path: Path,
        *,
        on_disk: list[str],
        in_agents_md: list[tuple[str, str, str]] | None = None,
    ) -> Path:
        for name in on_disk:
            _make_git(tmp_path / name)
        if in_agents_md is not None:
            lines = ["# Workspace", "", "## Repos", "",
                     "| Repo | One-line | Lang |", "|---|---|---|"]
            for name, oneline, lang in in_agents_md:
                lines.append(f"| [`{name}`](./{name}) | {oneline} | {lang} |")
            _write(tmp_path / "AGENTS.md", "\n".join(lines) + "\n")
        return tmp_path

    def test_basic_enrichment(self, tmp_path: Path) -> None:
        self._make_workspace_with_agents(
            tmp_path,
            on_disk=["alpha", "beta"],
            in_agents_md=[
                ("alpha", "Alpha service", "Python"),
                ("beta", "Beta library", "Rust"),
            ],
        )
        result = detect(tmp_path)
        by_name = {r.name: r for r in result.repos}
        assert by_name["alpha"].display_name == "Alpha service"
        assert by_name["alpha"].description == "Python"
        assert by_name["beta"].display_name == "Beta library"

    def test_drift_missing_from_disk(self, tmp_path: Path) -> None:
        self._make_workspace_with_agents(
            tmp_path,
            on_disk=["alpha", "beta"],
            in_agents_md=[
                ("alpha", "Alpha", "Python"),
                ("beta", "Beta", "Rust"),
                ("gamma", "Gamma (not checked out)", "Go"),
            ],
        )
        result = detect(tmp_path)
        drifts = [d for d in result.drift_warnings if d.kind == "missing_from_disk"]
        assert len(drifts) == 1
        assert drifts[0].agents_md_path == "./gamma"

    def test_drift_missing_from_agents(self, tmp_path: Path) -> None:
        self._make_workspace_with_agents(
            tmp_path,
            on_disk=["alpha", "beta", "extra"],
            in_agents_md=[
                ("alpha", "Alpha", "Python"),
                ("beta", "Beta", "Rust"),
            ],
        )
        result = detect(tmp_path)
        drifts = [d for d in result.drift_warnings if d.kind == "missing_from_agents"]
        assert len(drifts) == 1
        assert drifts[0].detected_path == "./extra"

    def test_no_agents_md_means_no_drift(self, tmp_path: Path) -> None:
        for name in ("alpha", "beta"):
            _make_git(tmp_path / name)
        result = detect(tmp_path)
        assert result.classification == "multi_repo_workspace"
        assert result.drift_warnings == []
        assert all(r.display_name is None for r in result.repos)


# ---------- envelope shape ---------------------------------------------


class TestEnvelopeShape:
    """Wire format: detect_v1. Stability matters for the MCP/skill consumers."""

    def test_to_dict_round_trip(self, tmp_path: Path) -> None:
        _make_git(tmp_path)
        result = detect(tmp_path)
        d = result.to_dict()
        assert d["version"] == DETECT_VERSION
        assert set(d.keys()) >= {
            "version", "classification", "confidence", "root",
            "repos", "drift_warnings", "signals",
        }
        for r in d["repos"]:
            assert {"name", "path", "rel_path", "has_git",
                    "display_name", "description"} <= set(r.keys())

    def test_root_is_absolute(self, tmp_path: Path) -> None:
        # Pass a relative path; the result must be absolute.
        _make_git(tmp_path)
        cwd = Path.cwd()
        try:
            os.chdir(tmp_path)
            result = detect(Path("."))
        finally:
            os.chdir(cwd)
        assert Path(result.root).is_absolute()


# ---------- error path --------------------------------------------------


class TestErrors:
    def test_not_a_directory_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "nope.txt"
        bad.write_text("hi")
        with pytest.raises(NotADirectoryError):
            detect(bad)


# ---------- dogfood -----------------------------------------------------


class TestDogfood:
    """Detector run against this very repo should classify as single_repo.

    Sanity check that nothing in the agent-readiness checkout (vendored
    rules pack, plugin hooks, fixtures dir at the engine root) trips
    the monorepo signals. If this regresses, the engine PR is shipping
    a false positive for itself.
    """

    def test_agent_readiness_root_is_single_repo(self) -> None:
        # Walk up from this test file to the repo root.
        here = Path(__file__).resolve()
        # tests/ → repo root
        root = here.parent.parent
        # Only run when invoked from a checkout (not from an installed wheel).
        if not (root / ".git").exists():
            pytest.skip("not running inside a git checkout")
        result = detect(root)
        assert result.classification == "single_repo", (
            f"agent-readiness root classified as {result.classification} "
            f"with signals {result.signals['fired']!r} — this would block "
            f"`agent-readiness scan .` on the engine repo itself."
        )
