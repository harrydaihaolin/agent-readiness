"""Load YAML rule files into LoadedRule objects with version gating.

The loader is intentionally permissive about *what* it can load — any
file under ``rules/`` that parses as YAML and matches the expected top-
level shape — but strict about *what version* it accepts. Rules with a
``rules_version`` outside the loader's supported range are dropped with
a warning; loaders shipped with old clients won't try to interpret rules
they don't understand.

We import the ``Rule`` pydantic model from the protocol package when it
is installed, otherwise fall back to a tiny dataclass — this keeps
agent-readiness usable without the optional protocol dep at install
time, while still enforcing the schema when it's available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# The loader supports this set of rules_version integers. Bumping
# this is a coordinated change with the protocol package.
SUPPORTED_RULES_VERSIONS: frozenset[int] = frozenset({1})


class RuleLoadError(ValueError):
    """Raised on a malformed YAML file (cannot be parsed at all)."""


@dataclass(frozen=True)
class LoadedRule:
    """A rule that loaded successfully and is safe to evaluate."""

    rule_id: str
    pillar: str
    title: str
    weight: float
    severity: str
    explanation: str
    match: dict[str, Any]
    fix_hint: str | None
    insight_query: str | None
    source_path: Path

    @property
    def match_type(self) -> str:
        return str(self.match.get("type", ""))


def _load_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment issue
        raise RuleLoadError("PyYAML is required to load rules; pip install pyyaml") from exc
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise RuleLoadError("rule YAML must be a mapping at the top level")
    return parsed


def _try_validate_with_protocol(data: dict[str, Any]) -> None:
    """Best-effort validation against the protocol's pydantic Rule model.

    If the protocol package isn't installed, skip validation — the
    consumer just gets the looser load. We don't want agent-readiness
    to hard-require the protocol pkg; rules_eval works either way.
    """
    try:
        from agent_readiness_insights_protocol import Rule  # type: ignore[import-not-found]
    except ImportError:
        return
    Rule.model_validate(data)


def load_rule_file(path: Path) -> LoadedRule | None:
    """Load one rule file; return None if version-gated out."""
    text = path.read_text()
    data = _load_yaml(text)

    rules_version = data.get("rules_version")
    if not isinstance(rules_version, int):
        raise RuleLoadError(f"{path}: missing or non-integer 'rules_version'")
    if rules_version not in SUPPORTED_RULES_VERSIONS:
        logger.warning(
            "skipping %s: rules_version=%s is not in supported set %s",
            path, rules_version, sorted(SUPPORTED_RULES_VERSIONS),
        )
        return None

    _try_validate_with_protocol(data)

    match = data.get("match")
    if not isinstance(match, dict):
        raise RuleLoadError(f"{path}: 'match' must be a mapping")

    return LoadedRule(
        rule_id=str(data["id"]),
        pillar=str(data["pillar"]),
        title=str(data.get("title", data["id"])),
        weight=float(data.get("weight", 1.0)),
        severity=str(data.get("severity", "warn")),
        explanation=str(data.get("explanation", "")).strip(),
        match=match,
        fix_hint=data.get("fix_hint"),
        insight_query=data.get("insight_query"),
        source_path=path,
    )


def load_rules_from_dir(rules_dir: Path) -> list[LoadedRule]:
    """Load every ``*.yaml`` under ``rules_dir`` recursively.

    Files that fail to parse are skipped with a logged error; we do NOT
    crash the whole load on one bad file. Files that are version-gated
    out simply aren't returned.
    """
    out: list[LoadedRule] = []
    if not rules_dir.is_dir():
        return out
    for path in sorted(rules_dir.rglob("*.yaml")):
        try:
            rule = load_rule_file(path)
        except RuleLoadError as exc:
            logger.error("failed to load %s: %s", path, exc)
            continue
        if rule is not None:
            out.append(rule)
    return out
