"""Replay ``events.jsonl`` into a :class:`WorkspaceScanSnapshot`.

Served by ``GET /api/scans/<scan_id>/snapshot``. Lets a reconnecting
browser paint without re-consuming the entire SSE stream — open the
snapshot, then start the SSE subscription at ``snapshot.last_seq + 1``.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from agent_readiness_insights_protocol import (
    PromptRecord,
    RepoFindingCounts,
    ScanChild,
    WorkspaceScanSnapshot,
)

from agent_readiness.live_scan.events import iter_events
from agent_readiness.live_scan.paths import workspace_hash


def build_snapshot(scan_dir: Path, workspace_path: Path) -> WorkspaceScanSnapshot:
    """Materialize the current snapshot by folding over events.jsonl.

    Deterministic: replaying the same log on a fresh scan_dir produces
    the same snapshot byte-for-byte.
    """
    scan_dir = Path(scan_dir)

    snap_scan_id = workspace_hash(workspace_path)
    last_seq = 0
    status: str = "queued"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    children: list[ScanChild] = []
    repo_states: dict[str, str] = {}
    repo_scores: dict[str, float] = {}
    repo_finding_counts: dict[str, RepoFindingCounts] = {}

    overall_score: Optional[float] = None
    pillar_scores: dict[str, float] = {}

    pending_prompts_records: dict[str, PromptRecord] = {}
    answered_or_expired: set[str] = set()
    default_used_for: list[str] = []

    mode_exit_requested = False
    exit_source: Optional[str] = None

    for ev in iter_events(scan_dir):
        seq = ev.get("seq")
        if isinstance(seq, int):
            last_seq = max(last_seq, seq)
        kind = ev.get("event")

        if kind == "scan.queued":
            children = [
                ScanChild(id=c["id"], name=c["name"], path=c["path"])
                for c in ev.get("children", [])
            ]
            for c in children:
                repo_states.setdefault(c.id, "queued")
        elif kind == "scan.started":
            status = "running"
            started_at = _parse_dt(ev.get("started_at"))
        elif kind == "scan.completed":
            status = "completed"
            overall_score = ev.get("overall_score")
            pillar_scores = dict(ev.get("pillar_scores") or {})
            completed_at = _parse_dt(ev.get("at"))
        elif kind == "scan.exited":
            status = "exited"
            mode_exit_requested = True
            exit_source = ev.get("source")
            completed_at = _parse_dt(ev.get("at"))
        elif kind == "repo.queued":
            repo_states[ev["repo_id"]] = "queued"
        elif kind == "repo.scan.started":
            repo_states[ev["repo_id"]] = "scanning"
        elif kind == "repo.scan.completed":
            rid = ev["repo_id"]
            repo_states[rid] = "completed"
            if "score" in ev:
                repo_scores[rid] = ev["score"]
            counts = ev.get("finding_counts") or {}
            repo_finding_counts[rid] = RepoFindingCounts(
                warn=counts.get("warn", 0),
                error=counts.get("error", 0),
                not_measured=counts.get("not_measured", 0),
            )
        elif kind == "repo.scan.failed":
            repo_states[ev["repo_id"]] = "failed"
        elif kind == "workspace.score.tick":
            overall_score = ev.get("overall_score", overall_score)
            if ev.get("pillar_scores"):
                pillar_scores.update(ev["pillar_scores"])
        elif kind == "prompt.requested":
            rec = PromptRecord(
                seq=ev["seq"],
                event="requested",
                prompt_id=ev["prompt_id"],
                at=_parse_dt(ev["at"]) or datetime.utcnow(),
                blocking=ev.get("blocking", False),
                payload=ev.get("payload"),
                default_action=ev.get("default_action"),
            )
            pending_prompts_records[ev["prompt_id"]] = rec
        elif kind == "prompt.answered":
            pid = ev["prompt_id"]
            if pid in pending_prompts_records:
                pending_prompts_records.pop(pid, None)
            answered_or_expired.add(pid)
        elif kind == "prompt.expired":
            pid = ev["prompt_id"]
            if pid in pending_prompts_records:
                pending_prompts_records.pop(pid, None)
            if pid not in default_used_for:
                default_used_for.append(pid)
            answered_or_expired.add(pid)
        # log.line, repo.evaluator.tick, repo.finding.added — silent
        # in snapshot (live-feed-only data).

    snap = WorkspaceScanSnapshot(
        scan_id=snap_scan_id,
        last_seq=last_seq,
        workspace_path=str(workspace_path),
        status=status,  # type: ignore[arg-type]
        started_at=started_at,
        completed_at=completed_at,
        children=children,
        repo_states=repo_states,  # type: ignore[arg-type]
        repo_scores=repo_scores,
        repo_finding_counts=repo_finding_counts,
        overall_score=overall_score,
        pillar_scores=pillar_scores,
        pending_prompts=list(pending_prompts_records.values()),
        default_used_for=default_used_for,
        mode_exit_requested=mode_exit_requested,
        exit_source=exit_source,  # type: ignore[arg-type]
    )
    return snap


def _parse_dt(raw) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            # Pydantic emits ISO-8601 with offset; fromisoformat handles it.
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
