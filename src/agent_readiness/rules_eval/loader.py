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
# this is a coordinated change with the protocol package. v2 adds
# the deterministic action contract (action + verify blocks); v1
# rules continue to load during the transition window so a stale
# rules-pack pin doesn't break consumers the day v2 ships.
SUPPORTED_RULES_VERSIONS: frozenset[int] = frozenset({1, 2})


class RuleLoadError(ValueError):
    """Raised on a malformed YAML file (cannot be parsed at all)."""


@dataclass(frozen=True)
class LoadedRule:
    """A rule that loaded successfully and is safe to evaluate.

    For ``rules_version >= 2`` rules, ``action`` and ``verify`` are
    populated dicts (matching the protocol's ``Action`` and
    ``VerifyStep`` shapes). For v1 rules they are ``None`` and
    consumers fall back to ``fix_hint`` text only.

    ``namespace`` is an optional sub-pillar register. Today it is used
    only by the Ontology pillar, which splits its rules into two
    registers:

    * ``schema``     — declaration-presence assertions ("does the
      workspace declare X?"). Usually satisfied by adding a file or
      a manifest field.
    * ``validation`` — runtime invariants over the typed graph
      ("do the declarations hold together?"). Usually needs
      cross-instance evaluation, not a single-file fix.

    Pass-through metadata; nothing in the evaluator branches on it
    yet. Future consumers: gap-aware MCP tools (Bundle B of the
    2026-05-26 ontology-driven-agent design) and the ontology
    inference reasoner (Bundle C). Other pillars may opt in later;
    ``None`` means the rule sits at pillar level only.

    ``confidence`` is the per-rule confidence level the rule author
    declares for the auto-fix. It drives the engine's
    ``apply_top_action`` branching:

    * ``high``   — apply the fix immediately (the v3.1 behaviour).
    * ``medium`` — refuse to apply; return a ``confirm_required``
      envelope so the MCP layer's ``confirm_apply`` tool can finish
      the round-trip with the user in the loop. This is the default
      so rule authors must opt in to ``high`` deliberately.
    * ``low``    — refuse to apply; return a ``gap_payload`` envelope
      so the MCP layer can record a Gap and surface it on the next
      scan via ``ontology.gaps_unresolved``.

    The engine propagates this value onto every ``Finding`` the rule
    produces (see ``Finding.confidence``). Added in agent-readiness
    v3.2.0 / protocol v0.9.0.
    """

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
    rules_version: int = 1
    action: dict[str, Any] | None = None
    verify: dict[str, Any] | None = None
    fix_prompt: str | None = None
    applies_when: dict[str, Any] | None = None
    namespace: str | None = None
    confidence: str = "medium"

    @property
    def match_type(self) -> str:
        return str(self.match.get("type", ""))


# Closed set of accepted ``namespace`` values, mirroring the protocol's
# ``Rule.namespace`` Literal. Kept here (not imported from the protocol)
# so the engine still loads when the optional protocol dep isn't
# installed — same pattern as the rest of this loader.
_VALID_NAMESPACES: frozenset[str] = frozenset({"schema", "validation", "inference"})

# Closed set of accepted ``confidence`` values, mirroring the protocol's
# ``Rule.confidence`` Literal. Same rationale as ``_VALID_NAMESPACES``:
# enforce the closed-world contract even when the optional protocol
# dependency isn't installed in the consumer's environment.
_VALID_CONFIDENCES: frozenset[str] = frozenset({"high", "medium", "low"})


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

    If the protocol *is* installed but rejects the rule (typically
    because the user has an older protocol release that pre-dates a
    schema extension like ``PrivateMatch``), log a warning and skip.
    The rule's own structural fields are still loaded by the
    permissive ``LoadedRule`` dataclass downstream, and unknown
    ``match.type`` values gracefully degrade to ``not_measured`` in
    the evaluator. Failing the entire scan because the user's
    protocol pin is one minor version behind would be the wrong
    trade-off — best-effort means best-effort.
    """
    try:
        from agent_readiness_insights_protocol import Rule  # type: ignore[import-not-found]
    except ImportError:
        return
    try:
        Rule.model_validate(data)
    except Exception as exc:  # noqa: BLE001 -- pydantic raises a family
        # Use debug, not warning: ``CliRunner`` mixes stderr into stdout
        # by default, and a noisy warning here would contaminate
        # ``--json`` output with log lines and break downstream parsers.
        # The evaluator already graceful-degrades unknown match types to
        # ``not_measured``, so this is purely diagnostic.
        logger.debug(
            "protocol validation rejected rule (continuing with looser "
            "load); upgrade agent-readiness-insights-protocol to silence: %s",
            exc,
        )


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

    action = data.get("action")
    if action is not None and not isinstance(action, dict):
        raise RuleLoadError(f"{path}: 'action' must be a mapping or null")
    verify = data.get("verify")
    if verify is not None and not isinstance(verify, dict):
        raise RuleLoadError(f"{path}: 'verify' must be a mapping or null")

    fix_prompt = data.get("fix_prompt")
    if fix_prompt is not None and not isinstance(fix_prompt, str):
        raise RuleLoadError(f"{path}: 'fix_prompt' must be a string or null")

    applies_when = data.get("applies_when")
    if applies_when is not None and not isinstance(applies_when, dict):
        raise RuleLoadError(f"{path}: 'applies_when' must be a mapping or null")

    namespace = data.get("namespace")
    if namespace is not None and namespace not in _VALID_NAMESPACES:
        raise RuleLoadError(
            f"{path}: 'namespace' must be one of {sorted(_VALID_NAMESPACES)} "
            f"or null; got {namespace!r}"
        )

    confidence = data.get("confidence", "medium")
    if confidence not in _VALID_CONFIDENCES:
        raise RuleLoadError(
            f"{path}: 'confidence' must be one of {sorted(_VALID_CONFIDENCES)}; "
            f"got {confidence!r}"
        )

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
        rules_version=rules_version,
        action=action,
        verify=verify,
        fix_prompt=fix_prompt,
        applies_when=applies_when,
        namespace=namespace,
        confidence=confidence,
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
