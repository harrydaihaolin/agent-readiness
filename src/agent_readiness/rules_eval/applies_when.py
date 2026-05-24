"""Predicate evaluation for the ``applies_when`` rule selector.

A rule's ``applies_when`` mapping is an *AND* over its keys (each key
is a predicate name; the value is the predicate's argument). If every
predicate is ``True`` against the current ``RepoContext`` the rule
runs as usual; if any predicate is ``False`` the evaluator short-
circuits the rule to ``not_measured=True`` (no findings, no score
contribution).

Predicates registered here in v1:

- ``any_language_detected: bool`` — ``True`` iff
  ``len(ctx.detected_languages) > 0``. Use to skip code-ecosystem
  rules on YAML-only / docs-only / config-only repos.
- ``languages_in: list[str]`` — ``True`` iff *any* detected language
  is in the list. Use for ecosystem-specific rules
  (e.g. ``[python, rust]`` for a Python-or-Rust rule).

Unknown predicate keys log a warning and evaluate to ``False`` so that
a rules-pack pinned ahead of the engine cannot silently change
behaviour by adding new predicate keys the engine doesn't yet know
about.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from agent_readiness.context import RepoContext


logger = logging.getLogger(__name__)


Predicate = Callable[[RepoContext, Any], bool]


def _pred_any_language_detected(ctx: RepoContext, value: Any) -> bool:
    """``any_language_detected: true`` → at least one language detected."""
    expected = bool(value)
    detected = len(ctx.detected_languages) > 0
    return detected is expected


def _pred_languages_in(ctx: RepoContext, value: Any) -> bool:
    """``languages_in: [python, rust]`` → any detected language is listed."""
    if not isinstance(value, (list, tuple)):
        logger.warning(
            "applies_when.languages_in must be a list, got %r — predicate False",
            type(value).__name__,
        )
        return False
    allowed = {str(v).lower() for v in value}
    detected = {lang.lower() for lang in ctx.detected_languages}
    return bool(detected & allowed)


_PREDICATES: dict[str, Predicate] = {
    "any_language_detected": _pred_any_language_detected,
    "languages_in":          _pred_languages_in,
}


def rule_applies(
    applies_when: dict[str, Any] | None,
    ctx: RepoContext,
) -> bool:
    """Return ``True`` if the rule should run against ``ctx``.

    ``None`` / empty dict → rule always applies (backwards compatible).
    Any predicate evaluating to ``False`` short-circuits the rule.
    Unknown predicates evaluate to ``False`` (closed-world: a rules-pack
    pin ahead of the engine cannot silently enable new predicates).
    """
    if not applies_when:
        return True
    for key, value in applies_when.items():
        predicate = _PREDICATES.get(key)
        if predicate is None:
            logger.warning(
                "unknown applies_when predicate %r — treating as False; "
                "upgrade agent-readiness to silence",
                key,
            )
            return False
        if not predicate(ctx, value):
            return False
    return True


__all__ = ["rule_applies"]
