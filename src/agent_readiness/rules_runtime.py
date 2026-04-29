"""Thin convenience layer over ``agent_readiness.rules_eval``.

The CLI, the scaffold command, and the MCP server all need the same
two operations:

1.  Locate the active rules pack (vendored snapshot today; pip dep
    after Q1 phase 4) and load every YAML rule out of it.
2.  Look up a single rule by ``rule_id`` (used by ``explain`` and
    ``scaffold`` to map a check id to its metadata).

Putting them in one place keeps the consumers boring and gives the
phase-4 cutover a single function to swap.
"""

from __future__ import annotations

from pathlib import Path

from agent_readiness.rules_eval import LoadedRule, load_rules_from_dir
from agent_readiness.rules_pack_loader import default_rules_dir


def load_default_rules(rules_dir: Path | None = None) -> list[LoadedRule]:
    """Load every YAML rule from ``rules_dir`` (or the vendored snapshot).

    Returns an empty list if no rules dir is available — the CLI prints
    a friendlier error than crashing on an empty list, and tests can
    inject their own rules via the ``rules_dir`` argument.
    """
    chosen = rules_dir if rules_dir is not None else default_rules_dir()
    if chosen is None or not chosen.is_dir():
        return []
    return load_rules_from_dir(chosen)


def get_rule(rule_id: str, rules: list[LoadedRule] | None = None) -> LoadedRule | None:
    """Return the rule with the given ``rule_id``, or None.

    ``rules`` defaults to ``load_default_rules()``; pass an explicit
    list to avoid repeated disk loads in hot paths.
    """
    if rules is None:
        rules = load_default_rules()
    for r in rules:
        if r.rule_id == rule_id:
            return r
    return None


__all__ = ["load_default_rules", "get_rule"]
