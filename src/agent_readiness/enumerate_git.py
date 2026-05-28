"""Git-aware enumeration: find every .git under a root, prune noise.

Replaces the depth-1 ``agent_readiness.enumerate`` rubric for the
dashboard onboarding flow. See spec
``agent-readiness-research/docs/superpowers/specs/
2026-05-27-dashboard-onboarding-design.md`` § 6.2.

Strategy
--------
1. POSIX fast path: shell out to ``find`` with ``-prune`` for the
   standard noise dirs. Single subprocess, no Python-level iteration
   over millions of paths.
2. Fallback: pure Python ``os.walk`` with in-place ``dirs[:]`` pruning.
   Used on Windows or when ``find`` is missing.

Both strategies share the same `_emit_candidate` step that builds a
``RepoCandidate`` from a found ``.git`` marker.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from agent_readiness_insights_protocol import (
    EnumerationResult,
    InspectResult,
    OnboardingClassification,
    RepoCandidate,
)

PRUNE_NAMES: frozenset[str] = frozenset({
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "target",
    "build",
    "__pycache__",
    ".tox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
})


def enumerate_git_repos(root: Path) -> EnumerationResult:
    """Walk ``root`` to find every ``.git`` marker, pruning noise dirs.

    Returns an :class:`EnumerationResult` with the candidates sorted by
    path for deterministic rendering."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"path is not a directory: {root}")

    start = time.perf_counter()
    if shutil.which("find") is not None and os.name != "nt":
        repos, dirs_walked = _find_strategy(root)
    else:
        repos, dirs_walked = _walk_strategy(root)

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    # Detect whether root itself is a repo.
    root_has_git = (root / ".git").exists()

    # Stable ordering for the dashboard.
    repos.sort(key=lambda r: r.path)

    return EnumerationResult(
        root=str(root),
        root_has_git=root_has_git,
        repos=repos,
        directories_walked=dirs_walked,
        elapsed_ms=elapsed_ms,
    )


def _find_strategy(root: Path) -> tuple[list[RepoCandidate], int]:
    """POSIX fast path: shell out to `find` once."""
    prune_args: list[str] = []
    for i, name in enumerate(sorted(PRUNE_NAMES)):
        if i > 0:
            prune_args.append("-o")
        prune_args.extend(["-name", name])

    cmd = [
        "find", str(root),
        "(", "-type", "d", "(", *prune_args, ")", "-prune", ")",
        "-o", "-name", ".git", "-print",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    candidate_paths: list[Path] = []
    for line in proc.stdout.splitlines():
        marker = Path(line.rstrip())
        if marker.name == ".git" and marker.parent != root:
            candidate_paths.append(marker.parent)
        elif marker.name == ".git" and marker.parent == root:
            # root has .git — we still record it for has_git detection,
            # but it is NOT a child candidate.
            pass

    # find does not stop at repo boundaries; drop nested .git markers.
    candidate_paths = _drop_nested_candidates(candidate_paths)

    # Cheap dirs-walked metric: count distinct parent dirs we saw.
    dirs_walked = max(1, len({p.parent for p in candidate_paths}) + len(candidate_paths))

    repos = [_emit_candidate(p) for p in candidate_paths]
    return repos, dirs_walked


def _drop_nested_candidates(paths: list[Path]) -> list[Path]:
    """Keep only shallowest repo paths when find discovers nested .git markers."""
    paths = sorted(paths, key=lambda p: len(p.parts))
    kept: list[Path] = []
    for p in paths:
        if not any(p != k and str(p).startswith(str(k) + os.sep) for k in kept):
            kept.append(p)
    return kept


def _walk_strategy(root: Path) -> tuple[list[RepoCandidate], int]:
    """Fallback: pure `os.walk` with in-place pruning."""
    repos: list[RepoCandidate] = []
    dirs_walked = 0

    for dirpath, dirs, files in os.walk(root, followlinks=False):
        dirs_walked += 1
        # Prune noise.
        dirs[:] = [d for d in dirs if d not in PRUNE_NAMES]

        # Skip the root itself for repo detection (handled by root_has_git).
        if Path(dirpath) == root:
            continue

        if ".git" in dirs or ".git" in files:
            repos.append(_emit_candidate(Path(dirpath)))
            # Don't recurse into the found repo.
            dirs[:] = []

    return repos, dirs_walked


def _emit_candidate(repo_path: Path) -> RepoCandidate:
    """Build a ``RepoCandidate`` from a directory known to contain ``.git``."""
    has_readme = any((repo_path / f).exists() for f in ("README.md", "README.rst", "readme.md"))
    has_pyproject = (repo_path / "pyproject.toml").exists()
    has_package_json = (repo_path / "package.json").exists()
    has_agents_md = (repo_path / "AGENTS.md").exists()
    size_kb = _dir_size_kb(repo_path)
    language_guess = _guess_language(repo_path, has_pyproject, has_package_json)
    last_commit = _last_commit_relative(repo_path)
    return RepoCandidate(
        path=str(repo_path),
        name=repo_path.name,
        has_git=True,
        has_readme=has_readme,
        has_pyproject=has_pyproject,
        has_package_json=has_package_json,
        has_agents_md=has_agents_md,
        size_kb=size_kb,
        language_guess=language_guess,
        last_commit=last_commit,
    )


def _dir_size_kb(p: Path) -> int:
    """Best-effort recursive size. Skips noise dirs to stay fast."""
    total = 0
    for dirpath, dirs, files in os.walk(p, followlinks=False):
        dirs[:] = [d for d in dirs if d not in PRUNE_NAMES]
        for fname in files:
            fpath = Path(dirpath) / fname
            try:
                total += fpath.stat().st_size
            except OSError:
                pass
    return total // 1024


def _guess_language(p: Path, has_pyproject: bool, has_package_json: bool) -> str | None:
    if has_pyproject:
        return "Python"
    if has_package_json:
        return "TypeScript" if (p / "tsconfig.json").exists() else "JavaScript"
    if (p / "Cargo.toml").exists():
        return "Rust"
    if (p / "go.mod").exists():
        return "Go"
    return None


def _last_commit_relative(p: Path) -> str | None:
    """`git log -1 --format=%cr` if git is available and `p` is a repo."""
    if shutil.which("git") is None:
        return None
    proc = subprocess.run(
        ["git", "-C", str(p), "log", "-1", "--format=%cr"],
        capture_output=True, text=True, check=False, timeout=2,
    )
    out = proc.stdout.strip()
    return out or None


def classify(
    root_has_git: bool,
    repos_found: int,
    children_with_git: int,
) -> OnboardingClassification:
    """Five-branch counting rubric. Returns the suggested workspace type
    plus a confidence label and one-line rationale.

    Branches:
        root has .git, no nested  -> single_repo / high
        root has .git, ≥1 nested  -> monorepo / medium
        no root .git, exactly 1   -> single_repo / high  (nested-in-wrapper)
        no root .git, ≥2 nested   -> workspace / medium
        no .git anywhere          -> single_repo / low   (will scan as dir)
    """
    if root_has_git and children_with_git == 0:
        return OnboardingClassification(
            suggested_type="single_repo",
            confidence="high",
            rationale="Root has .git, no nested repos.",
        )
    if root_has_git and children_with_git >= 1:
        return OnboardingClassification(
            suggested_type="monorepo",
            confidence="medium",
            rationale=f"Root has .git AND {children_with_git} nested .git — likely monorepo with vendored submodules or workspaces.",
        )
    if not root_has_git and repos_found == 1:
        return OnboardingClassification(
            suggested_type="single_repo",
            confidence="high",
            rationale="Root has no .git but exactly one nested .git — single repo nested in a wrapper.",
        )
    if not root_has_git and repos_found >= 2:
        return OnboardingClassification(
            suggested_type="workspace",
            confidence="medium",
            rationale=f"Root has no .git, {repos_found} nested .git — looks like a workspace of independent repos.",
        )
    return OnboardingClassification(
        suggested_type="single_repo",
        confidence="low",
        rationale="No .git anywhere; will scan as a single directory.",
    )


def inspect(root: Path) -> InspectResult:
    """One-shot: enumerate then classify. Used by the `inspect` CLI and
    MCP tool. Cheap enough to call every time — no caching."""
    enumeration = enumerate_git_repos(root)
    classification = classify(
        root_has_git=enumeration.root_has_git,
        repos_found=len(enumeration.repos),
        children_with_git=sum(1 for r in enumeration.repos if r.has_git),
    )
    return InspectResult(enumeration=enumeration, classification=classification)
