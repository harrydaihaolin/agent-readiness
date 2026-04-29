"""Private matcher: ``tree_aggregate``.

Two YAML modes:
- ``mode: top_level_count`` — fires when count of non-meta root files
  exceeds ``warn_above``. Used by ``repo_shape.top_level_count``.
- ``mode: orientation_tokens`` — fires when ``RepoContext.orientation_tokens``
  exceeds ``warn_tokens``. Used by ``repo_shape.token_budget``. Honours
  ``token_budget_warn`` / ``token_budget_max`` overrides from the
  repo's ``.agent-readiness.toml`` (consistent with the original Python
  check) when YAML config doesn't override.
"""

from __future__ import annotations

from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher


def _top_level_count_mode(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    warn_above = int(cfg.get("warn_above", 20))
    exclude_dotfiles = bool(cfg.get("exclude_dotfiles", True))
    exclude_stems = {s.lower() for s in (cfg.get("exclude_stems") or [])}

    def _is_meta(name: str) -> bool:
        return name.lower().split(".")[0] in exclude_stems

    count = sum(
        1 for f in ctx._files
        if len(f.parts) == 1
        and (not exclude_dotfiles or not f.name.startswith("."))
        and (not exclude_stems or not _is_meta(f.name))
    )
    if count <= warn_above:
        return []
    return [(
        None, None,
        f"Repo root has {count} non-meta files — consider organising into subdirectories.",
    )]


def _orientation_tokens_mode(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    # YAML-supplied thresholds take precedence; otherwise honour the
    # repo's .agent-readiness.toml overrides (matches the original
    # Python check's behaviour).
    warn_tokens = int(
        cfg.get("warn_tokens", ctx.context_config.get("token_budget_warn", 24_000))
    )
    tokens = ctx.orientation_tokens
    if tokens <= warn_tokens:
        return []
    return [(
        None, None,
        f"Estimated orientation cost is ~{tokens:,} tokens — may exceed agent context window.",
    )]


def match_tree_aggregate(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    mode = str(cfg.get("mode", ""))
    if mode == "top_level_count":
        return _top_level_count_mode(ctx, cfg)
    if mode == "orientation_tokens":
        return _orientation_tokens_mode(ctx, cfg)
    return []


register_private_matcher("tree_aggregate", match_tree_aggregate)
