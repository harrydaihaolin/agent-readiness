"""Scoring: turn check results into pillar scores and an overall score.

Rules (from RUBRIC.md):

- Each pillar's score is a weighted arithmetic mean of its non-skipped
  check scores. Checks marked `not_measured` are excluded from the
  denominator, not scored as zero.
- If a pillar has zero non-skipped checks, its score is reported as
  100.0 (nothing to dock) and noted via `not_measured` flags downstream.
- The overall score is a weighted mean of the three weighted pillars
  (Cognitive Load, Feedback, Flow). Safety is NOT in the weighted sum.
- Safety findings can cap the overall score:
    error-severity safety findings  -> overall capped at SAFETY_CAP_HARD (30)
    warn-severity safety findings   -> overall capped at SAFETY_CAP_SOFT (75)
  The cap is applied after the weighted-mean computation. The amount the
  cap took off is recorded on the Report for transparency.
"""

from __future__ import annotations

from agent_readiness.models import (
    CheckResult,
    Finding,
    Pillar,
    PillarScore,
    Report,
    Severity,
)
from pathlib import Path
from typing import Any


# Default pillar weights. Configurable via .agent-readiness.toml later.
DEFAULT_WEIGHTS: dict[Pillar, float] = {
    Pillar.FEEDBACK: 0.40,
    Pillar.COGNITIVE_LOAD: 0.30,
    Pillar.FLOW: 0.30,
    # Safety intentionally absent — applied as a cap, not weighted.
}

SAFETY_CAP_HARD = 30.0  # any error-severity safety finding
SAFETY_CAP_SOFT = 75.0  # any warn-severity safety finding

# EXP-4 top-action priority. Same severity tier first, then this pillar
# order, then the per-rule weight (descending). The order intentionally
# puts FLOW above FEEDBACK above SAFETY above COGNITIVE_LOAD because:
#   FLOW   — broken builds/setup block every other fix
#   FEEDBACK — once setup works, the agent needs a reliable test signal
#   SAFETY — non-error safety is mostly hygiene; errors already escalated
#            to the top by the severity tier above
#   COGNITIVE_LOAD — refactor work, generally last to do.
# Severity does the heavy lifting (errors always win); pillar order only
# breaks ties between same-severity findings.
_PILLAR_PRIORITY: dict[Pillar, int] = {
    Pillar.FLOW:           0,
    Pillar.FEEDBACK:       1,
    Pillar.SAFETY:         2,
    Pillar.COGNITIVE_LOAD: 3,
}

_SEVERITY_PRIORITY: dict[Severity, int] = {
    Severity.ERROR: 0,
    Severity.WARN:  1,
    Severity.INFO:  2,
}


def _weighted_mean(results: list[CheckResult]) -> float:
    """Weighted mean of measured check scores. 100.0 if none measured."""
    measured = [r for r in results if not r.not_measured]
    if not measured:
        return 100.0
    total_weight = sum(r.weight for r in measured)
    if total_weight <= 0:
        return 100.0
    return sum(r.score * r.weight for r in measured) / total_weight


def score(repo_path: Path, results: list[CheckResult],
          weights: dict[Pillar, float] | None = None) -> Report:
    """Aggregate check results into a Report."""
    weights = weights or DEFAULT_WEIGHTS

    # Group by pillar (preserve registration order within a pillar).
    by_pillar: dict[Pillar, list[CheckResult]] = {p: [] for p in Pillar}
    for r in results:
        by_pillar.setdefault(r.pillar, []).append(r)

    pillar_scores = [
        PillarScore(pillar=p, score=_weighted_mean(by_pillar[p]),
                    check_results=by_pillar[p])
        for p in Pillar
    ]

    # Weighted overall across the three weighted pillars.
    weighted_pillars = [ps for ps in pillar_scores if ps.pillar in weights]
    total_w = sum(weights[ps.pillar] for ps in weighted_pillars) or 1.0
    raw_overall = sum(ps.score * weights[ps.pillar] for ps in weighted_pillars) / total_w

    # Safety cap: walk all safety findings across all results.
    # ERROR findings apply the hard cap (30); WARN findings apply a
    # weight-modulated soft cap — higher-weight checks (more severe signals)
    # produce a stricter cap, while lower-weight checks are more lenient.
    cap = 100.0
    for ps in pillar_scores:
        if ps.pillar is not Pillar.SAFETY:
            continue
        for cr in ps.check_results:
            for f in cr.findings:
                if f.severity is Severity.ERROR:
                    cap = min(cap, SAFETY_CAP_HARD)
                elif f.severity is Severity.WARN:
                    soft_range = 100.0 - SAFETY_CAP_SOFT  # = 25
                    effective_soft = SAFETY_CAP_SOFT + (1.0 - cr.weight) * soft_range
                    cap = min(cap, effective_soft)

    overall = min(raw_overall, cap)
    safety_cap_applied = (raw_overall - overall) if overall < raw_overall else None

    # Populate score_impact on each check: estimated overall-score gain from fixing.
    # Safety checks influence via cap, not the weighted sum, so their impact is 0.
    for ps in pillar_scores:
        pillar_w = weights.get(ps.pillar, 0.0)
        w_fraction = pillar_w / total_w if total_w > 0 else 0.0
        for cr in ps.check_results:
            if cr.not_measured or ps.pillar is Pillar.SAFETY:
                cr.score_impact = 0.0
            else:
                cr.score_impact = round((100.0 - cr.score) * cr.weight * w_fraction, 1)

    report = Report(
        repo_path=repo_path,
        overall_score=round(overall, 1),
        pillar_scores=pillar_scores,
        safety_cap_applied=round(safety_cap_applied, 1) if safety_cap_applied else None,
    )
    report.top_action = compute_top_action(report)
    return report


def compute_top_action(report: Report) -> dict[str, Any] | None:
    """Pick the per-repo "Start here" action.

    Priority:
        severity (error < warn < info)
            -> pillar [flow < feedback < safety < cognitive_load]
            -> weight desc (higher weight = higher priority)
            -> stable check_id

    Returns ``None`` when the repo has zero findings. Otherwise returns
    a JSON-shaped dict the leaderboard / report card consumes directly:

        {"check_id": ...,
         "pillar":   ...,
         "severity": ...,
         "message":  ...,
         "weight":   1.0,
         "rationale": "<one-line: why this finding wins>",
         "fix_hint": "...",          # only when present
         "action":  {...},           # only when the rule is rules_version=2
         "verify":  {...}}

    Coverage gate (from EXP-4): every repo with >=1 finding gets a
    non-null ``top_action``. We do NOT filter on the action contract —
    legacy v1 rules without a structured action still surface their
    fix_hint as the pin so the agent isn't left empty-handed during the
    rules-pack v1 -> v2 transition.
    """
    candidates: list[tuple[int, int, float, str, str, Finding, CheckResult]] = []
    for ps in report.pillar_scores:
        pillar_rank = _PILLAR_PRIORITY[ps.pillar]
        for cr in ps.check_results:
            if cr.not_measured:
                continue
            for f in cr.findings:
                sev_rank = _SEVERITY_PRIORITY[f.severity]
                candidates.append((
                    sev_rank,
                    pillar_rank,
                    -float(cr.weight),       # negative = sort high-weight first
                    cr.check_id,
                    f.message,
                    f,
                    cr,
                ))
    if not candidates:
        return None

    candidates.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    sev_rank, pillar_rank, neg_weight, check_id, _msg, finding, cr = candidates[0]

    rationale_parts: list[str] = []
    if finding.severity is Severity.ERROR:
        rationale_parts.append("error severity")
    elif finding.severity is Severity.WARN:
        rationale_parts.append("highest pillar priority among warn findings")
    else:
        rationale_parts.append(f"highest pillar priority ({cr.pillar.value})")
    if cr.weight != 1.0:
        rationale_parts.append(f"weight {cr.weight:.2f}")
    rationale = "; ".join(rationale_parts)

    payload: dict[str, Any] = {
        "check_id": cr.check_id,
        "pillar":   cr.pillar.value,
        "severity": finding.severity.value,
        "message":  finding.message,
        "weight":   cr.weight,
        "rationale": rationale,
    }
    if finding.fix_hint:
        payload["fix_hint"] = finding.fix_hint
    if finding.action is not None:
        payload["action"] = finding.action
    if finding.verify is not None:
        payload["verify"] = finding.verify
    return payload
