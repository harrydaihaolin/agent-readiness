"""Scan worker loop: sequential per-child scanning with live envelope writes.

Wraps the existing ``workspace_scan._scan_one_child`` (reused unchanged so
scoring stays byte-identical to today's headless ``workspace-scan``).
"""
from __future__ import annotations

import signal
import time
from dataclasses import dataclass
from pathlib import Path

from agent_readiness.live_scan import envelope as env_mod
from agent_readiness.live_scan import history as hist_mod
from agent_readiness.live_scan.paths import scan_dir, workspace_hash
from agent_readiness.live_scan.pidfile import clear_pidfile, write_pidfile


HARD_TIMEOUT_S_DEFAULT = 60 * 60  # 60 minutes


@dataclass
class ScanOptions:
    hard_timeout_s: int = HARD_TIMEOUT_S_DEFAULT


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

    try:
        for child in children:
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
            child_dict = _safe_scan_one_child(child, envelope)
            if child_dict is not None:
                env_mod.add_completed_child(envelope, child_dict)
            env_mod.write_envelope(sd, envelope)

        env_mod.set_status(envelope, "completed")
        envelope["stats"]["scan_duration_ms"] = int(
            (time.monotonic() - started_mono) * 1000
        )
        _finalize_aggregate(envelope, workspace_path)
        env_mod.write_envelope(sd, envelope)

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
