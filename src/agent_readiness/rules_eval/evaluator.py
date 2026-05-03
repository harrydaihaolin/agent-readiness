"""Run a list of LoadedRule objects against a RepoContext.

Returns CheckResult objects shaped exactly like the @register checks,
so the scorer can mix rule-pack findings with built-in check findings
in the same Report. No schema bump needed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity

from .loader import LoadedRule
from .matchers import OssMatchTypeRegistry

logger = logging.getLogger(__name__)


_PILLAR_LOOKUP = {p.value: p for p in Pillar}
_SEV_LOOKUP = {s.value: s for s in Severity}


def _to_pillar(name: str) -> Pillar:
    p = _PILLAR_LOOKUP.get(name.lower())
    if p is None:
        # Default to FLOW for unknown — better than crashing.
        logger.warning("unknown pillar %r, defaulting to flow", name)
        return Pillar.FLOW
    return p


def _to_severity(name: str) -> Severity:
    return _SEV_LOOKUP.get(name.lower(), Severity.WARN)


def evaluate_rule(rule: LoadedRule, ctx: RepoContext) -> CheckResult:
    """Evaluate one rule. Returns a CheckResult; unknown match types
    produce a `not_measured=True` result with no findings.
    """
    pillar = _to_pillar(rule.pillar)
    severity = _to_severity(rule.severity)
    matcher = OssMatchTypeRegistry.get(rule.match_type)
    if matcher is None:
        # Unknown match type (likely a private match type from the engine).
        # Don't fail — just don't measure it on the OSS path.
        return CheckResult(
            check_id=rule.rule_id,
            pillar=pillar,
            score=100.0,
            weight=rule.weight,
            not_measured=True,
            findings=[],
            explanation=rule.explanation or None,
        )

    raw = matcher(ctx, rule.match)
    findings: list[Finding] = []
    for file_str, line, message in raw:
        findings.append(
            Finding(
                check_id=rule.rule_id,
                pillar=pillar,
                message=message,
                severity=severity,
                file=Path(file_str) if file_str else None,
                line=line,
                fix_hint=rule.fix_hint,
                action=rule.action,
                verify=rule.verify,
            )
        )

    # Score: 100 when no findings; for warnings, scale gently. The scorer
    # ultimately weights this; we just produce a coherent per-rule score.
    if not findings:
        score = 100.0
    elif severity == Severity.ERROR:
        score = 0.0
    elif severity == Severity.WARN:
        # Multiple findings degrade more, but cap at 30 (warn rules
        # shouldn't dominate the pillar score).
        score = max(30.0, 80.0 - 10.0 * (len(findings) - 1))
    else:  # info
        score = max(70.0, 90.0 - 5.0 * (len(findings) - 1))

    return CheckResult(
        check_id=rule.rule_id,
        pillar=pillar,
        score=score,
        weight=rule.weight,
        findings=findings,
        explanation=rule.explanation or None,
    )


def evaluate_rules(rules: list[LoadedRule], ctx: RepoContext) -> list[CheckResult]:
    """Evaluate every rule against ctx; return a CheckResult per rule."""
    return [evaluate_rule(r, ctx) for r in rules]
