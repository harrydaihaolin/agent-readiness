"""Static enumeration of a directory's children for workspace classification.

Pure-Python. No scoring, no rule evaluation, no LLM. Returns enough
structure for a downstream caller (the skill prompt) to decide whether
the path is a single repo, monorepo, workspace, or none of the above.

See docs/superpowers/specs/2026-05-23-workspace-scan-coordination-pillar-design.md
"""
from __future__ import annotations

from pathlib import Path

from agent_readiness.models import ChildEnumeration, EnumerationReport

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
    return EnumerationReport(
        root=root,
        children=children,
        manifest_signals=_detect_manifest_signals(path),
        stats=stats,
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
    """Static fast-path hints: 'this is obviously a monorepo' signals."""
    signals = {
        "pnpm_workspace":           (root / "pnpm-workspace.yaml").exists(),
        "cargo_workspace":          False,
        "pyproject_workspace":      False,
        "package_json_workspaces":  False,
        "gradle_multi":             (root / "settings.gradle").exists()
                                    or (root / "settings.gradle.kts").exists(),
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


def _safe_read(p: Path, max_bytes: int = 64_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except (OSError, UnicodeDecodeError):
        return ""
