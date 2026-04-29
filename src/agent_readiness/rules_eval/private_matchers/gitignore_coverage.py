"""Private matcher: ``gitignore_coverage``.

Multi-regex bucket scoring: groups the YAML config asks about are
matched against the repo's ``.gitignore`` text. Fires once with a
list of *missing* groups when fewer than ``min_groups_covered`` are
present. Fires once with a "no .gitignore" finding when the file is
absent.
"""

from __future__ import annotations

import re
from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher

# Built-in named groups. YAML rules can reference these by name in
# ``groups: [python_pycache, node_modules, ...]``. A custom rule can
# instead supply a fully-explicit ``custom_groups: [{name, patterns}]``.
_BUILTIN_GROUPS: dict[str, tuple[re.Pattern[str], ...]] = {
    "python_pycache": (re.compile(r"__pycache__"), re.compile(r"\*\.pyc")),
    "node_modules":   (re.compile(r"node_modules"),),
    "dotenv":         (re.compile(r"\.env\b"),),
    "dist_build":     (re.compile(r"^/?dist/", re.M), re.compile(r"^/?build/", re.M)),
    "go_vendor":      (re.compile(r"^/?vendor/", re.M), re.compile(r"\*\.exe\b")),
    "rust_target":    (re.compile(r"^/?target/", re.M),),
    "jvm_class":      (re.compile(r"\*\.class\b"),),
    "ide_junk":       (
        re.compile(r"\.idea/"),
        re.compile(r"\.DS_Store"),
        re.compile(r"\*\.swp\b"),
        re.compile(r"\.vscode/"),
    ),
    "python_egg_info": (re.compile(r"\.egg-info/"), re.compile(r"^/?\.eggs/", re.M)),
    "coverage":       (
        re.compile(r"^/?\.coverage\b", re.M),
        re.compile(r"^/?htmlcov/", re.M),
        re.compile(r"^/?\.pytest_cache/", re.M),
        re.compile(r"^/?coverage/", re.M),
    ),
    "swift_build":    (re.compile(r"^/?\.build/", re.M), re.compile(r"DerivedData")),
    "terraform":      (re.compile(r"^/?\.terraform/", re.M), re.compile(r"\*\.tfstate\b")),
    "logs":           (re.compile(r"\*\.log\b"),),
}


def match_gitignore_coverage(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    gitignore_path = ctx.root / ".gitignore"
    if not gitignore_path.is_file():
        return [(
            ".gitignore", None,
            "No .gitignore found.",
        )]

    text = gitignore_path.read_text(encoding="utf-8", errors="replace")

    requested = list(cfg.get("groups") or _BUILTIN_GROUPS.keys())
    min_required = int(cfg.get("min_groups_covered", 7))

    missing: list[str] = []
    for name in requested:
        patterns = _BUILTIN_GROUPS.get(name)
        if patterns is None:
            # Unknown group name — count as missing so callers can't
            # silently drop coverage by typoing a group.
            missing.append(name)
            continue
        if not any(pat.search(text) for pat in patterns):
            missing.append(name)

    covered = len(requested) - len(missing)
    if covered >= min_required:
        return []

    return [(
        ".gitignore", None,
        f".gitignore covers {covered}/{len(requested)} groups; missing: {', '.join(missing)}.",
    )]


register_private_matcher("gitignore_coverage", match_gitignore_coverage)
