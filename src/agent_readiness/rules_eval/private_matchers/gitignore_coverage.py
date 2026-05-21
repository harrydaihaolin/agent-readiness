"""Private matcher: ``gitignore_coverage``.

Multi-regex bucket scoring: groups the YAML config asks about are
matched against the repo's ``.gitignore`` text. Fires once with a
list of *missing* groups when fewer than ``min_groups_covered`` are
present. Fires once with a "no .gitignore" finding when the file is
absent.

When ``language_aware: true`` is set, the matcher resolves the repo's
primary language (via the same probe ``context_probe`` uses) and
filters the requested groups down to *universal* groups (always
required) plus the *per-language* groups for the detected stack. A
Scala-only repo no longer fails because it doesn't ignore
``node_modules/`` or ``__pycache__/``; a Python+Node monorepo still
gets both checked.
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


# Universal groups are *always* required when ``language_aware: true``.
# Every repo, regardless of language, runs binaries that emit logs, gets
# touched by an IDE, and risks leaking ``.env`` secrets — so these three
# groups are non-negotiable.
_UNIVERSAL_GROUPS: frozenset[str] = frozenset({"dotenv", "ide_junk", "logs"})

# Per-language groups. The matcher requires every group in the *union*
# of detected languages' rows. ``""`` (no language detected) falls back
# to "all groups" — preserves the pre-language-aware behaviour for
# repos the engine can't classify.
#
# The terraform group is treated as a language so an infra repo can opt
# into it via ``primary_language=terraform``; we don't have a probe for
# that yet, so terraform fires only when explicitly listed.
_LANGUAGE_GROUPS: dict[str, frozenset[str]] = {
    "python":     frozenset({"python_pycache", "python_egg_info", "dist_build", "coverage"}),
    "javascript": frozenset({"node_modules", "dist_build", "coverage"}),
    "typescript": frozenset({"node_modules", "dist_build", "coverage"}),
    "go":         frozenset({"go_vendor"}),
    "rust":       frozenset({"rust_target"}),
    "java":       frozenset({"jvm_class", "dist_build"}),
    "kotlin":     frozenset({"jvm_class", "dist_build"}),
    "scala":      frozenset({"jvm_class", "rust_target"}),  # SBT/Mill use `target/`
    "clojure":    frozenset({"jvm_class", "rust_target"}),  # lein uses `target/`
    "swift":      frozenset({"swift_build"}),
    "elixir":     frozenset({"dist_build"}),                # mix uses `_build/` → matches dist_build re-only loosely; fine
    "dart":       frozenset({"dist_build"}),
    "haskell":    frozenset({"dist_build"}),                # stack uses `.stack-work/`; not perfectly captured today
    "ruby":       frozenset({"coverage"}),
    "php":        frozenset({"coverage"}),
    "cpp":        frozenset({"dist_build"}),                # cmake -B build/
}


def _required_groups(
    requested: list[str], detected_languages: set[str]
) -> list[str]:
    """Resolve which groups must be covered under language_aware mode.

    - Always include universal groups present in ``requested``.
    - For each detected language, include its language-specific groups
      that appear in ``requested``.
    - If no language was detected, fall back to the full request list
      (mirrors the pre-language-aware behaviour so we don't silently
      under-fire on unclassified repos).
    """
    if not detected_languages:
        return list(requested)
    requested_set = set(requested)
    required: set[str] = set()
    required |= _UNIVERSAL_GROUPS & requested_set
    for lang in detected_languages:
        required |= _LANGUAGE_GROUPS.get(lang, frozenset()) & requested_set
    # Preserve the request order so the message reads predictably.
    return [g for g in requested if g in required]


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
    min_required_cfg = int(cfg.get("min_groups_covered", 7))
    language_aware = bool(cfg.get("language_aware", False))

    # Under language_aware mode the effective requested set is the
    # universal + detected-language groups; ``min_required`` then means
    # "all of these required groups must be present" (i.e. it's
    # implicitly the size of the filtered set, not the YAML number).
    if language_aware:
        # Local import keeps the matcher module free of any heavy
        # imports at engine startup; the probe is cheap.
        from agent_readiness.rules_eval.context_probe import (
            _detect_primary_language,
        )

        primary = _detect_primary_language(ctx)
        detected = {primary} if primary else set()
        effective_requested = _required_groups(requested, detected)
        min_required = len(effective_requested)
    else:
        effective_requested = requested
        min_required = min_required_cfg

    missing: list[str] = []
    for name in effective_requested:
        patterns = _BUILTIN_GROUPS.get(name)
        if patterns is None:
            # Unknown group name — count as missing so callers can't
            # silently drop coverage by typoing a group.
            missing.append(name)
            continue
        if not any(pat.search(text) for pat in patterns):
            missing.append(name)

    covered = len(effective_requested) - len(missing)
    if covered >= min_required:
        return []

    return [(
        ".gitignore", None,
        f".gitignore covers {covered}/{len(effective_requested)} groups; missing: {', '.join(missing)}.",
    )]


register_private_matcher("gitignore_coverage", match_gitignore_coverage)
