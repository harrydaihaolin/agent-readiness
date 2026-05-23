"""Workspace-level readiness scan.

Runs the Coordination pack at the workspace root, runs the existing
per-repo scan logic on each child path, and aggregates the results
into a single :class:`WorkspaceReadinessReport`.

See docs/superpowers/specs/2026-05-23-workspace-scan-coordination-pillar-design.md
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent_readiness.coordination import evaluate_coordination
from agent_readiness.models import (
    CheckResult,
    ChildReadiness,
    Finding,
    Severity,
    WorkspaceReadinessReport,
)


def scan(path: Path, children: list[Path]) -> WorkspaceReadinessReport:
    """Run a workspace-level readiness scan.

    Args:
        path: Workspace root (where Coordination checks evaluate).
        children: Child paths the caller (skill) has classified as
            workspace members. Must be non-empty; the skill is the
            right place to enumerate and classify.

    Returns:
        :class:`WorkspaceReadinessReport` with 5 pillar scores, per-child
        cards, and a ``top_action`` whose ``scope`` is ``"workspace"``
        (Coordination beats child) or ``"child"`` (worst child's
        top_action promoted with ``child_path`` stamped on).
    """
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"path is not a directory: {path}")
    if not children:
        raise ValueError("children list must be non-empty for workspace-scan")

    started = time.monotonic()

    # 1. Coordination pack at the root.
    coordination_results = evaluate_coordination(path, children)
    coordination_findings: list[Finding] = []
    for cr in coordination_results:
        coordination_findings.extend(cr.findings)
    coordination_score = _score_coordination(coordination_results)

    # 2. Per-child scans (sequential; parallel is a deliberate non-goal).
    child_reports: list[ChildReadiness] = []
    failed_paths: list[str] = []
    safety_caps_applied: list[dict[str, Any]] = []

    for child_path in children:
        child_path = child_path.expanduser().resolve()
        if not child_path.is_dir():
            failed_paths.append(str(child_path))
            continue
        try:
            report = _scan_one_child(child_path)
        except Exception:
            failed_paths.append(str(child_path))
            continue
        child_reports.append(report)
        if report.safety_cap_applied is not None:
            safety_caps_applied.append({
                "child": child_path.name,
                "cap": report.safety_cap_applied,
            })

    # 3. Aggregation.
    pillar_scores = _aggregate_pillar_scores(child_reports, coordination_score)
    overall = _overall_score(pillar_scores)

    # 4. Top-action selection — Coordination beats child.
    top_action = _pick_top_action(coordination_findings, child_reports)

    stats = {
        "children_scanned": len(child_reports),
        "children_failed": len(failed_paths),
        "children_failed_paths": failed_paths,
        "scan_duration_ms": int((time.monotonic() - started) * 1000),
    }

    return WorkspaceReadinessReport(
        repo_path=path,
        overall_score=overall,
        pillar_scores=pillar_scores,
        children=child_reports,
        coordination_findings=coordination_findings,
        top_action=top_action,
        stats=stats,
        safety_caps_applied=safety_caps_applied,
    )


# --- per-child scan adapter --------------------------------------------

def _scan_one_child(child_path: Path) -> ChildReadiness:
    """Run the existing per-repo scan against ``child_path``."""
    from agent_readiness.context import RepoContext
    from agent_readiness.rules_eval import evaluate_rules
    from agent_readiness.rules_runtime import load_default_rules
    from agent_readiness.scorer import score as score_results

    rules = load_default_rules()
    ctx = RepoContext(root=child_path)
    rule_results: list[CheckResult] = []
    for rule in rules:
        rule_results.extend(evaluate_rules([rule], ctx))
    report = score_results(child_path, rule_results)

    pillar_scores: dict[str, float] = {}
    for ps in report.pillar_scores:
        pillar_scores[ps.pillar.value] = ps.score

    return ChildReadiness(
        path=child_path,
        overall_score=report.overall_score,
        pillar_scores=pillar_scores,
        safety_cap_applied=report.safety_cap_applied,
        top_action=report.top_action,
    )


# --- scoring + aggregation --------------------------------------------

def _score_coordination(results: list[CheckResult]) -> float:
    """Coordination pillar score: mean of per-check scores.

    Each v1 Coordination check is 0 or 100, so the mean is equivalent
    to the standard scorer when all weights are 1.0. Swap for the full
    scorer when partial-credit Coordination checks land.
    """
    if not results:
        return 100.0
    return sum(r.score for r in results) / len(results)


def _aggregate_pillar_scores(
    child_reports: list[ChildReadiness],
    coordination_score: float,
) -> dict[str, float]:
    """Mean of post-cap child scores per pillar; coordination from root."""
    pillars = ["cognitive_load", "feedback", "flow", "safety"]
    out: dict[str, float] = {}
    for p in pillars:
        if not child_reports:
            out[p] = 0.0
            continue
        scores = [c.pillar_scores.get(p, 0.0) for c in child_reports]
        out[p] = sum(scores) / len(scores)
    out["coordination"] = coordination_score
    return out


def _overall_score(pillar_scores: dict[str, float]) -> float:
    """Arithmetic mean of all 5 pillar scores."""
    if not pillar_scores:
        return 0.0
    return sum(pillar_scores.values()) / len(pillar_scores)


def _pick_top_action(
    coordination_findings: list[Finding],
    child_reports: list[ChildReadiness],
) -> dict[str, Any] | None:
    """Workspace > child priority.

    Coordination WARN/ERROR findings always win over any per-child
    top_action — workspace-level orientation is upstream of per-repo
    issues. With no Coordination findings, the worst child's
    ``top_action`` is promoted with ``scope="child"`` and the child's
    path stamped on.
    """
    warn_or_worse = [
        f for f in coordination_findings
        if f.severity in (Severity.WARN, Severity.ERROR)
    ]
    if warn_or_worse:
        warn_or_worse.sort(
            key=lambda f: (
                0 if f.severity is Severity.ERROR else 1,
                f.check_id,
            )
        )
        f = warn_or_worse[0]
        return {
            "scope": "workspace",
            "child_path": None,
            "check_id": f.check_id,
            "pillar": f.pillar.value,
            "severity": f.severity.value,
            "message": f.message,
            "action": f.action,
            "verify": f.verify,
        }

    candidates = [c for c in child_reports if c.top_action is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda c: c.overall_score)
    worst = candidates[0]
    inner = dict(worst.top_action or {})
    inner["scope"] = "child"
    inner["child_path"] = str(worst.path)
    return inner
