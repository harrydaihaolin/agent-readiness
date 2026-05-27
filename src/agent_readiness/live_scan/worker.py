"""Scan worker loop: sequential per-child scanning with live envelope writes.

Wraps the existing ``workspace_scan._scan_one_child`` (reused unchanged so
scoring stays byte-identical to today's headless ``workspace-scan``).

Bundle D extension: optionally emits SSE events through an ``EventLog``
passed via :class:`ScanOptions`. When ``event_log`` is None the worker
behaves exactly as before (no events.jsonl writes), so existing
non-dashboard callers see no behaviour change.
"""
from __future__ import annotations

import hashlib
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent_readiness_insights_protocol import (
    RepoFindingCounts,
    RepoQueuedEvent,
    RepoScanCompletedEvent,
    RepoScanFailedEvent,
    RepoScanStartedEvent,
    ScanChild,
    ScanCompletedEvent,
    ScanQueuedEvent,
    ScanStartedEvent,
    WorkspaceScoreTickEvent,
)

from agent_readiness.live_scan import envelope as env_mod
from agent_readiness.live_scan import history as hist_mod
from agent_readiness.live_scan.events import EventLog
from agent_readiness.live_scan.paths import scan_dir, workspace_hash
from agent_readiness.live_scan.pidfile import clear_pidfile, write_pidfile


HARD_TIMEOUT_S_DEFAULT = 60 * 60  # 60 minutes


def _repo_id(child_path: Path) -> str:
    """Stable per-scan repo id. Short hash of the absolute path so the
    same child across re-scans collides intentionally; useful for the
    SSE consumer to dedup state across restarts."""
    return hashlib.sha1(str(child_path.resolve()).encode("utf-8")).hexdigest()[:10]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScanOptions:
    hard_timeout_s: int = HARD_TIMEOUT_S_DEFAULT
    event_log: Optional[EventLog] = None  # Bundle D: SSE wire


def scan_workspace(
    workspace_path: Path,
    children: list[Path],
    options: ScanOptions | None = None,
) -> dict:
    """Run a workspace scan with live envelope writes. Returns final envelope.

    Sequential v1; Spec 2 lifts to parallel. Catches per-child errors and
    appends to ``stats.children_failed_paths``. Honors SIGINT and SIGTERM
    by marking ``status=cancelled`` and exiting cleanly between children.
    """
    options = options or ScanOptions()
    sd = scan_dir(workspace_path)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "archive").mkdir(exist_ok=True)
    wh = workspace_hash(workspace_path)

    envelope = env_mod.new_envelope(workspace_path, total_children=len(children))
    env_mod.write_envelope(sd, envelope)
    write_pidfile(sd / "daemon.pid", scan_id=wh)

    # Bundle D — emit lifecycle events.
    bus = options.event_log
    child_ids = [_repo_id(Path(c)) for c in children]
    if bus is not None:
        bus.emit(ScanQueuedEvent(
            seq=bus.next_seq,
            at=_now_utc(),
            workspace_path=str(workspace_path.resolve()),
            children=[
                ScanChild(
                    id=cid,
                    name=Path(c).name,
                    path=str(Path(c).resolve()),
                )
                for cid, c in zip(child_ids, children)
            ],
            total=len(children),
        ))
        for cid in child_ids:
            bus.emit(RepoQueuedEvent(seq=bus.next_seq, at=_now_utc(), repo_id=cid))
        bus.emit(ScanStartedEvent(seq=bus.next_seq, at=_now_utc(), started_at=_now_utc()))

    # Cancellation flag flipped by signal handlers — checked between children.
    cancel_requested = {"flag": False}

    def _on_signal(_sig, _frame):
        cancel_requested["flag"] = True

    # signal.signal() is main-thread-only; protect against being called from
    # a background thread (e.g. inside pytest with thread-scoped fixtures).
    try:
        orig_int = signal.signal(signal.SIGINT, _on_signal)
        orig_term = signal.signal(signal.SIGTERM, _on_signal)
        signals_installed = True
    except ValueError:
        orig_int = None
        orig_term = None
        signals_installed = False

    started_mono = time.monotonic()
    prev_overall: float = 0.0

    try:
        for child, cid in zip(children, child_ids):
            if cancel_requested["flag"]:
                env_mod.set_status(envelope, "cancelled")
                env_mod.write_envelope(sd, envelope)
                clear_pidfile(sd / "daemon.pid")
                return envelope
            if time.monotonic() - started_mono > options.hard_timeout_s:
                env_mod.set_status(envelope, "failed")
                envelope["stats"]["failure_reason"] = "timeout_exceeded"
                env_mod.write_envelope(sd, envelope)
                clear_pidfile(sd / "daemon.pid")
                return envelope
            child = Path(child).expanduser().resolve()
            env_mod.set_in_flight(envelope, [child])
            env_mod.write_envelope(sd, envelope)

            if bus is not None:
                bus.emit(RepoScanStartedEvent(
                    seq=bus.next_seq, at=_now_utc(),
                    repo_id=cid, started_at=_now_utc(),
                ))

            child_dict = _safe_scan_one_child(child, envelope)
            if child_dict is not None:
                env_mod.add_completed_child(envelope, child_dict)
                if bus is not None:
                    bus.emit(RepoScanCompletedEvent(
                        seq=bus.next_seq, at=_now_utc(),
                        repo_id=cid,
                        score=float(child_dict.get("overall_score") or 0.0),
                        pillar_scores={
                            k: float(v) for k, v in (child_dict.get("pillar_scores") or {}).items()
                        },
                        finding_counts=RepoFindingCounts(),  # populated later when scorer ships counts
                        completed_at=_now_utc(),
                    ))
                    # Tick the workspace rollup with the running aggregate.
                    rolling = sum(
                        float(c.get("overall_score") or 0.0)
                        for c in envelope["children"]
                    ) / max(1, len(envelope["children"]))
                    bus.maybe_emit(
                        WorkspaceScoreTickEvent(
                            seq=bus.next_seq, at=_now_utc(),
                            overall_score=rolling,
                            pillar_scores={},
                            delta=rolling - prev_overall,
                        ),
                        throttle_key=("workspace.score.tick", None),
                    )
                    prev_overall = rolling
            else:
                # Hard failure on this child.
                if bus is not None:
                    bus.emit(RepoScanFailedEvent(
                        seq=bus.next_seq, at=_now_utc(),
                        repo_id=cid,
                        error="scan_failed",
                    ))
            env_mod.write_envelope(sd, envelope)

        env_mod.set_status(envelope, "completed")
        envelope["stats"]["scan_duration_ms"] = int(
            (time.monotonic() - started_mono) * 1000
        )
        _finalize_aggregate(envelope, workspace_path)
        env_mod.write_envelope(sd, envelope)

        if bus is not None:
            bus.emit(ScanCompletedEvent(
                seq=bus.next_seq, at=_now_utc(),
                overall_score=float(envelope.get("overall_score") or 0.0),
                pillar_scores={
                    k: float(v) for k, v in (envelope.get("pillar_scores") or {}).items()
                },
                top_action=envelope.get("top_action"),
            ))

        ts = hist_mod.archive_envelope(sd)
        hist_mod.register_scan(
            sd,
            workspace_path=str(workspace_path.resolve()),
            workspace_hash=wh,
            ts=ts,
            status=envelope["status"],
            overall=envelope.get("overall_score"),
        )
        hist_mod.prune_archive(sd)
        return envelope
    finally:
        if signals_installed:
            signal.signal(signal.SIGINT, orig_int)
            signal.signal(signal.SIGTERM, orig_term)
        clear_pidfile(sd / "daemon.pid")


def _safe_scan_one_child(child_path: Path, envelope: dict) -> dict | None:
    """Wrap ``_scan_one_child`` with error-to-failed-list translation."""
    from agent_readiness.workspace_scan import _scan_one_child
    if not child_path.is_dir():
        envelope["stats"]["children_failed_paths"].append(str(child_path))
        return None
    try:
        report = _scan_one_child(child_path)
    except Exception:
        envelope["stats"]["children_failed_paths"].append(str(child_path))
        return None
    return {
        "path": str(child_path),
        "overall_score": report.overall_score,
        "pillar_scores": report.pillar_scores,
        "safety_cap_applied": report.safety_cap_applied,
        "top_action": report.top_action,
    }


def _finalize_aggregate(envelope: dict, workspace_path: Path) -> None:
    """Compute aggregate pillar + overall scores once all children are in."""
    from agent_readiness.models import ChildReadiness
    from agent_readiness.workspace_scan import (
        _aggregate_pillar_scores,
        _overall_score,
        _score_ontology_at_root,
    )
    children_typed = [
        ChildReadiness(
            path=Path(c["path"]),
            overall_score=c["overall_score"],
            pillar_scores=c["pillar_scores"],
            safety_cap_applied=c["safety_cap_applied"],
            top_action=c["top_action"],
        )
        for c in envelope["children"]
    ]
    ontology = _score_ontology_at_root(Path(workspace_path).resolve())
    envelope["pillar_scores"] = _aggregate_pillar_scores(children_typed, ontology)
    envelope["overall_score"] = _overall_score(envelope["pillar_scores"])
