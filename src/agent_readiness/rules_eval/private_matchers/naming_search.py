"""Private matcher: ``naming_search``.

Fires per file whose stem (lowercase, sans extension) is in
``ambiguous_stems``, that lives at depth ≤ ``max_depth``, and whose
top-level parent is *not* in ``exclude_parent_dirs`` (because tests/
scripts/docs are conventional places to use generic utility names).
"""

from __future__ import annotations

from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher


def match_naming_search(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    ambiguous = {s.lower() for s in (cfg.get("ambiguous_stems") or [])}
    if not ambiguous:
        return []
    max_depth = int(cfg.get("max_depth", 2))
    max_findings = int(cfg.get("max_findings", 5))
    exclude_parents = {p.lower() for p in (cfg.get("exclude_parent_dirs") or [])}

    matches: list[str] = []
    for f in ctx._files:
        if f.stem.lower() not in ambiguous:
            continue
        if len(f.parts) > max_depth:
            continue
        if exclude_parents and len(f.parts) >= 2 and f.parts[0].lower() in exclude_parents:
            continue
        matches.append(str(f))

    return [
        (path, None, f"Ambiguously named file: {path}")
        for path in matches[:max_findings]
    ]


register_private_matcher("naming_search", match_naming_search)
