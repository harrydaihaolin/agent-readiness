"""Static enumeration of a directory's children for workspace classification.

Pure-Python. No scoring, no rule evaluation, no LLM. Returns enough
structure for a downstream caller (the skill prompt) to decide whether
the path is a single repo, monorepo, workspace, or none of the above.

See docs/superpowers/specs/2026-05-23-workspace-scan-coordination-pillar-design.md
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_readiness.models import (
    ChildEnumeration,
    ClassificationHint,
    EnumerationReport,
)

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "dist", "build",
    "target", ".cache", "__pycache__", ".tox", ".pytest_cache",
    ".mypy_cache", ".ruff_cache",
})

_MAX_TOP_FILES = 20
_MAX_TOP_DIRS = 20
_MAX_CHILDREN = 200


def enumerate_workspace(path: Path) -> EnumerationReport:
    """Enumerate ``path`` and its direct children for classification.

    Children are included iff they contain ``.git`` (dir or file) OR
    ``README.md`` (case-insensitive). Symlinks are not followed.
    Recursion is depth-1.
    """
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"path is not a directory: {path}")

    root = _enumerate_entry(path, include_manifests_for_lang=True)
    children: list[ChildEnumeration] = []
    truncated = False
    for entry in sorted(_iter_candidate_children(path)):
        if len(children) >= _MAX_CHILDREN:
            truncated = True
            break
        if _qualifies_as_child(entry):
            children.append(_enumerate_entry(entry, include_manifests_for_lang=True))

    stats = {
        "children_scanned": len(children),
        "children_with_git": sum(1 for c in children if c.has_git),
        "children_with_readme": sum(1 for c in children if c.has_readme),
        "scan_truncated": truncated,
    }
    signals = _detect_manifest_signals(path)
    hint = _classify(root, children, signals, stats)
    return EnumerationReport(
        root=root,
        children=children,
        manifest_signals=signals,
        stats=stats,
        classification_hint=hint,
    )


_ASK_OPTIONS_ROOT_AND_CHILDREN_HAVE_GIT: list[dict[str, str]] = [
    {
        "id": "workspace",
        "label": "Workspace of independent repos",
        "route": "scan_workspace_async",
        "hint": (
            "Each child is its own git repo with its own remote and "
            "release cycle. Launch the live dashboard."
        ),
    },
    {
        "id": "monorepo",
        "label": "Monorepo",
        "route": "scan_repo",
        "hint": (
            "One coherent project; the nested .git directories are "
            "submodules / vendored checkouts. Scan the root as one repo."
        ),
    },
    {
        "id": "single_repo",
        "label": "Single repo (treat root as one codebase)",
        "route": "scan_repo",
        "hint": (
            "The nested .git directories are unrelated; only the root "
            "matters for this scan."
        ),
    },
]


_ASK_OPTIONS_ONE_CHILD_WITH_GIT: list[dict[str, str]] = [
    {
        "id": "workspace",
        "label": "Workspace of one repo (expect more later)",
        "route": "scan_workspace_async",
        "hint": (
            "Treat the single child as a workspace member — useful "
            "when you are about to clone more siblings into the same "
            "parent."
        ),
    },
    {
        "id": "single_repo",
        "label": "Single repo (scan only the child)",
        "route": "scan_repo",
        "hint": (
            "The parent dir is just a holder; only the child needs "
            "scanning."
        ),
    },
]


_ASK_OPTIONS_NO_GIT_ANYWHERE: list[dict[str, str]] = [
    {
        "id": "skip",
        "label": "Skip — not a code repo",
        "route": "exit",
        "hint": "Documentation tree, downloads folder, or unrelated dir.",
    },
    {
        "id": "single_repo",
        "label": "Scan as a single repo anyway",
        "route": "scan_repo",
        "hint": "Pre-commit / brand-new project not yet under git.",
    },
]


def _classify(
    root: ChildEnumeration,
    children: list[ChildEnumeration],
    signals: dict[str, bool],
    stats: dict[str, Any],
) -> ClassificationHint:
    """Deterministic, signal-driven classification.

    Rules apply in strict order; the first match wins. Designed so the
    skill can route on ``recommended_action`` without LLM judgment.

    Rule order (first match wins):

    1. **Monorepo** — any ``manifest_signals.*`` is true. High confidence.
       Includes pnpm/cargo/pyproject/package-json workspaces and the
       "≥ 2 sibling manifests" convention monorepo signal.
    2. **Workspace of independents** — ``root.has_git == False`` AND
       ``stats.children_with_git >= 2``. High confidence; the dogfood
       case (no root repo, many sibling repos).
    3. **Single repo** — ``root.has_git == True`` AND
       ``stats.children_with_git == 0``. High confidence; the lone-repo
       case.
    4. **Not a code repo** — no ``.git`` anywhere AND no README AND no
       qualifying children. High confidence; route to exit.
    5. **Ambiguous: root + children both have ``.git``** — could be a
       workspace nested in a meta-repo, a monorepo with submodules, or
       a single repo with unrelated sub-checkouts. Signals cannot
       resolve this. Ask the user.
    6. **Ambiguous: single child with ``.git``** — possibly a workspace
       of one, possibly a misclassified single repo. Ask.
    7. **Ambiguous: no ``.git`` anywhere** — documentation tree or a
       brand-new project; ask whether to skip or scan-anyway.
    """
    if any(signals.values()):
        fired = [k for k, v in signals.items() if v]
        return ClassificationHint(
            classification="monorepo",
            confidence="high",
            recommended_action="scan_repo",
            rationale=f"manifest signals fired: {', '.join(fired)}",
        )

    n_with_git = stats.get("children_with_git", 0)

    if not root.has_git and n_with_git >= 2:
        return ClassificationHint(
            classification="workspace_of_independents",
            confidence="high",
            recommended_action="scan_workspace_async",
            rationale=(
                f"root has no .git AND {n_with_git} children have .git — "
                "classic workspace-of-independents layout"
            ),
        )

    if root.has_git and n_with_git == 0:
        return ClassificationHint(
            classification="single_repo",
            confidence="high",
            recommended_action="scan_repo",
            rationale="root .git only, no nested .git directories",
        )

    if (
        not root.has_git
        and not root.has_readme
        and stats.get("children_scanned", 0) == 0
    ):
        return ClassificationHint(
            classification="not_a_code_repo",
            confidence="high",
            recommended_action="exit",
            rationale="no .git, no README, no qualifying children",
        )

    if root.has_git and n_with_git >= 1:
        return ClassificationHint(
            classification="ambiguous",
            confidence="ambiguous",
            recommended_action="ask_user",
            rationale=(
                f"root has .git AND {n_with_git} children also have .git"
            ),
            ambiguity_reason=(
                "Root has a .git directory AND one or more children also "
                "have .git. This could be (a) a workspace of independent "
                "repos that someone put under its own meta-repo, (b) a "
                "monorepo where the nested .git dirs are submodules / "
                "vendored checkouts, or (c) a single repo whose subdirs "
                "happen to be unrelated git checkouts. The signals cannot "
                "tell these apart — only you can."
            ),
            ambiguity_options=_ASK_OPTIONS_ROOT_AND_CHILDREN_HAVE_GIT,
        )

    if not root.has_git and n_with_git == 1:
        return ClassificationHint(
            classification="ambiguous",
            confidence="ambiguous",
            recommended_action="ask_user",
            rationale="exactly one child has .git; root has no .git",
            ambiguity_reason=(
                "Only one child has .git and the root has no .git. This "
                "might be a workspace-of-one (more repos coming) or a "
                "regular single repo that happens to live under a holder "
                "directory."
            ),
            ambiguity_options=_ASK_OPTIONS_ONE_CHILD_WITH_GIT,
        )

    return ClassificationHint(
        classification="ambiguous",
        confidence="low",
        recommended_action="ask_user",
        rationale=(
            "no .git anywhere; "
            f"children_scanned={stats.get('children_scanned', 0)}"
        ),
        ambiguity_reason=(
            "No .git directories were found at the root or in any "
            "qualifying child. This is most likely a documentation tree "
            "or unrelated directory, but could be a brand-new project not "
            "yet under git."
        ),
        ambiguity_options=_ASK_OPTIONS_NO_GIT_ANYWHERE,
    )


def _iter_candidate_children(root: Path):
    """Yield direct children, skipping symlinks and ignore-list dirs."""
    try:
        entries = list(root.iterdir())
    except (PermissionError, OSError):
        return
    for e in entries:
        if e.is_symlink():
            continue
        if not e.is_dir():
            continue
        if e.name in _IGNORE_DIRS:
            continue
        yield e


def _qualifies_as_child(entry: Path) -> bool:
    """A child qualifies if it contains .git (dir or file) OR README.md."""
    if (entry / ".git").exists():
        return True
    for name in ("README.md", "readme.md", "README", "Readme.md"):
        if (entry / name).exists():
            return True
    return False


def _enumerate_entry(entry: Path, *, include_manifests_for_lang: bool) -> ChildEnumeration:
    has_git = (entry / ".git").exists()
    has_readme = any((entry / n).exists() for n in
                     ("README.md", "readme.md", "README", "Readme.md"))
    has_agents_md = any((entry / n).exists() for n in
                        ("AGENTS.md", "agents.md", "Agents.md"))
    top_files, top_dirs = _list_top_entries(entry)
    lang_hint = _language_hint(entry) if include_manifests_for_lang else []
    return ChildEnumeration(
        path=entry,
        has_git=has_git,
        has_readme=has_readme,
        has_agents_md=has_agents_md,
        top_files=top_files,
        top_dirs=top_dirs,
        language_hint=lang_hint,
    )


def _list_top_entries(entry: Path) -> tuple[list[str], list[str]]:
    files: list[str] = []
    dirs: list[str] = []
    try:
        items = sorted(entry.iterdir(), key=lambda p: p.name.lower())
    except (PermissionError, OSError):
        return [], []
    for item in items:
        if item.is_symlink():
            continue
        if item.is_dir():
            if item.name in _IGNORE_DIRS:
                continue
            if len(dirs) < _MAX_TOP_DIRS:
                dirs.append(item.name)
        else:
            if len(files) < _MAX_TOP_FILES:
                files.append(item.name)
    return files, dirs


def _language_hint(entry: Path) -> list[str]:
    """Cheap, top-level-only language detection from manifest presence."""
    langs: list[str] = []
    if (entry / "pyproject.toml").exists() or (entry / "setup.py").exists():
        langs.append("python")
    if (entry / "package.json").exists():
        if (entry / "tsconfig.json").exists():
            langs.append("typescript")
        else:
            langs.append("javascript")
    if (entry / "Cargo.toml").exists():
        langs.append("rust")
    if (entry / "go.mod").exists():
        langs.append("go")
    if (entry / "pom.xml").exists() or any(entry.glob("build.gradle*")):
        langs.append("jvm")
    if (entry / "mix.exs").exists():
        langs.append("elixir")
    return langs


def _detect_manifest_signals(root: Path) -> dict[str, bool]:
    """Static fast-path hints: 'this is obviously a monorepo' signals.

    Kept in lockstep with :py:attr:`RepoContext.monorepo_tools` so the
    enumerate / workspace-scan path and the per-repo scan path agree on
    what counts as a monorepo. The ``convention_monorepo`` signal —
    ≥ 2 direct-child manifest-bearing dirs — is what catches enterprise
    Python monorepos that pre-date ``uv`` / ``rye`` workspace
    declarations and stitch their N sibling packages together with a
    top-level Earthfile / Bazel / Jenkinsfile instead.
    """
    signals = {
        "pnpm_workspace":           (root / "pnpm-workspace.yaml").exists(),
        "cargo_workspace":          False,
        "pyproject_workspace":      False,
        "package_json_workspaces":  False,
        "gradle_multi":             (root / "settings.gradle").exists()
                                    or (root / "settings.gradle.kts").exists(),
        "convention_monorepo":      _count_sibling_manifests(root) >= 2,
    }
    cargo = root / "Cargo.toml"
    if cargo.exists():
        signals["cargo_workspace"] = "[workspace]" in _safe_read(cargo)
    pyproj = root / "pyproject.toml"
    if pyproj.exists():
        body = _safe_read(pyproj)
        signals["pyproject_workspace"] = (
            "[tool.uv.workspace]" in body
            or "[tool.rye.workspace]" in body
        )
    pkg = root / "package.json"
    if pkg.exists():
        signals["package_json_workspaces"] = '"workspaces"' in _safe_read(pkg)
    return signals


_MANIFEST_NAMES = (
    "pyproject.toml", "setup.py", "Cargo.toml", "package.json",
    "go.mod", "build.gradle", "build.gradle.kts", "pom.xml",
)


def _count_sibling_manifests(root: Path) -> int:
    """Count direct-child directories carrying their own manifest.

    Depth-1 only and existence-based — kept cheap so the enumerate
    fast-path stays sub-millisecond even on very wide repos.
    """
    count = 0
    try:
        for entry in root.iterdir():
            if entry.is_symlink() or not entry.is_dir():
                continue
            if entry.name in _IGNORE_DIRS:
                continue
            if any((entry / m).is_file() for m in _MANIFEST_NAMES):
                count += 1
    except OSError:
        return 0
    return count


def _safe_read(p: Path, max_bytes: int = 64_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except (OSError, UnicodeDecodeError):
        return ""
