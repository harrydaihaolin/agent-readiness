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
    Pillar,
    PillarScore,
    Report,
    Severity,
)
from pathlib import Path


# Default pillar weights. Configurable via .agent-readiness.toml later.
DEFAULT_WEIGHTS: dict[Pillar, float] = {
    Pillar.FEEDBACK: 0.40,
    Pillar.COGNITIVE_LOAD: 0.30,
    Pillar.FLOW: 0.30,
    # Safety intentionally absent — applied as a cap, not weighted.
}

SAFETY_CAP_HARD = 30.0  # any error-severity safety finding
SAFETY_CAP_SOFT = 75.0  # any warn-severity safety finding


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
    cap = 100.0
    for ps in pillar_scores:
        if ps.pillar is not Pillar.SAFETY:
            continue
        for cr in ps.check_results:
            for f in cr.findings:
                if f.severity is Severity.ERROR:
                    cap = min(cap, SAFETY_CAP_HARD)
                elif f.severity is Severity.WARN:
                    cap = min(cap, SAFETY_CAP_SOFT)

    overall = min(raw_overall, cap)
    safety_cap_applied = (raw_overall - overall) if overall < raw_overall else None

    return Report(
        repo_path=repo_path,
        overall_score=round(overall, 1),
        pillar_scores=pillar_scores,
        safety_cap_applied=round(safety_cap_applied, 1) if safety_cap_applied else None,
    )
