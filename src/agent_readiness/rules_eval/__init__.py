"""Reference (OSS) evaluator for declarative YAML rules.

This subpackage is the canonical interpretation of rule definitions
shipped in ``agent-readiness-rules``. The closed insights engine
implements its own evaluator with additional match types; the OSS
implementation here is what every Bronze user runs and what the
``agent-readiness-rules`` CI uses to validate new rules.

Public API:

    from agent_readiness.rules_eval import (
        load_rules_from_dir,
        evaluate_rules,
        OssMatchTypeRegistry,
        register_private_matcher,
    )

The OSS match types are:

- ``file_size``           — line/byte thresholds with glob exclusions
- ``path_glob``           — required/forbidden file globs
- ``manifest_field``      — fields in pyproject.toml / package.json
- ``regex_in_files``      — regex search in matched files
- ``command_in_makefile`` — Makefile target presence
- ``composite``           — boolean and/or/not over the leaf types above

Anything else (``ast_query``, ``churn_signal``, …) is treated as a
*private* match type. By default, unknown types produce a
``not_measured`` finding (see ``evaluator.evaluate_rule``) rather than
crashing — this lets a rules pack ship rules that only a downstream
engine knows how to evaluate. A downstream engine that *does* implement
such a type registers it via :func:`register_private_matcher` at import
time; the OSS evaluator then dispatches to the registered function.

Built-in OSS match types are immutable: ``register_private_matcher``
refuses to overwrite them.
"""

from __future__ import annotations

from typing import Callable

from .evaluator import evaluate_rules
from .loader import LoadedRule, RuleLoadError, load_rules_from_dir
from .matchers import MatcherFn, OssMatchTypeRegistry

# Snapshot of the OSS-shipped types at import time. Anything in this set
# is owned by the OSS evaluator and may not be replaced.
_OSS_BUILTIN_TYPES: frozenset[str] = frozenset(OssMatchTypeRegistry.keys())


def register_private_matcher(type_name: str, fn: MatcherFn) -> None:
    """Register a private (non-OSS) match type.

    Downstream engines (e.g. ``agent-readiness-pro``) call this at import
    time to teach the OSS evaluator how to dispatch a YAML rule whose
    ``match.type`` is something the OSS pack doesn't know — for example,
    ``ast_query``, ``churn_signal``, or any other proprietary analysis.

    Args:
        type_name: The string used in ``match.type`` in YAML rules.
        fn:        A ``MatcherFn`` ``(ctx, cfg) -> list[(file, line, msg)]``.

    Raises:
        ValueError: If ``type_name`` is one of the OSS built-ins. Those
            are immutable — overriding them would silently change OSS
            scan results, which is exactly the kind of surprise the
            ``not_measured`` fall-through is designed to prevent.
    """
    if type_name in _OSS_BUILTIN_TYPES:
        raise ValueError(
            f"cannot override built-in OSS match type {type_name!r}; "
            "private match types must use a distinct name"
        )
    OssMatchTypeRegistry[type_name] = fn


def unregister_private_matcher(type_name: str) -> bool:
    """Remove a previously-registered private matcher. Returns True if
    something was removed. OSS built-ins cannot be unregistered."""
    if type_name in _OSS_BUILTIN_TYPES:
        return False
    return OssMatchTypeRegistry.pop(type_name, None) is not None


# Re-exported alias for callers that prefer a typed handle to the
# matcher signature (see matchers.MatcherFn).
PrivateMatcherFn = Callable  # narrowed via MatcherFn at the call site


__all__ = [
    "LoadedRule",
    "RuleLoadError",
    "load_rules_from_dir",
    "evaluate_rules",
    "OssMatchTypeRegistry",
    "register_private_matcher",
    "unregister_private_matcher",
]
