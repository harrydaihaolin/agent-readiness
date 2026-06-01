"""Cross-workspace enumeration: ``list_scans`` + ``stop_all``."""
from __future__ import annotations

import json
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from agent_readiness.live_scan.paths import scans_root
from agent_readiness.live_scan.pidfile import (
    PidStatus,
    clear_pidfile,
    verify_pidfile,
)


def _dir_disk_bytes(p: Path) -> int:
    total = 0
    for sub in p.rglob("*"):
        if sub.is_file():
            try:
                total += sub.stat().st_size
            except OSError:
                pass
    return total


def list_scans() -> dict:
    """Enumerate active + recent scans across all workspaces."""
    root = scans_root()
    active: list[dict] = []
    recent: list[dict] = []
    total_bytes = 0
    if not root.exists():
        return {"active": active, "recent": recent, "total_disk_bytes": 0}
    for sd in sorted(root.iterdir()):
        if not sd.is_dir():
            continue
        total_bytes += _dir_disk_bytes(sd)
        scan_id = sd.name
        pid_path = sd / "daemon.pid"
        if verify_pidfile(pid_path) is PidStatus.LIVE:
            live = sd / "live.json"
            if live.exists():
                try:
                    env = json.loads(live.read_text())
                except json.JSONDecodeError:
                    env = {}
            else:
                env = {}
            url = ""
            if (sd / "server.url").exists():
                url = (sd / "server.url").read_text().strip()
            active.append({
                "scan_id": scan_id,
                "workspace_path": env.get("repo_path"),
                "started_at": env.get("started_at"),
                "dashboard_url": url,
                "progress": env.get("progress"),
                "log_file": str(sd / "scan.log"),
            })
        latest = sd / "latest.json"
        if latest.exists():
            try:
                env = json.loads(latest.read_text())
            except json.JSONDecodeError:
                continue
            recent.append({
                "scan_id": scan_id,
                "workspace_path": env.get("repo_path"),
                "completed_at": env.get("completed_at"),
                "overall_score": env.get("overall_score"),
                "disk_bytes": _dir_disk_bytes(sd),
            })
    recent.sort(key=lambda r: r.get("completed_at") or "", reverse=True)
    recent = recent[:50]
    return {"active": active, "recent": recent, "total_disk_bytes": total_bytes}


def build_workspace_index() -> dict:
    """Build a ``ScanIndex`` for the dashboard's History view (live mode).

    Groups every *completed* scan on this machine by ``workspace_path``
    into one ``WorkspaceSummary`` carrying the score ``trend_points``
    (oldest-first, last 10). Workspaces are ordered most-recently-scanned
    first. This is the live-mode equivalent of the static-export
    ``index.json`` — and, per the dashboard's no-client-aggregates rule,
    the grouping/trend math lives here in the scanner, not in the browser.
    """
    scans = list_scans()

    # Group completed scans by workspace, preserving newest-first order
    # (``recent`` is already sorted by completed_at descending).
    groups: dict[str, list[dict]] = {}
    for row in scans["recent"]:
        ws = row.get("workspace_path")
        if ws is None or row.get("overall_score") is None:
            continue
        groups.setdefault(ws, []).append(row)

    workspaces: list[dict] = []
    for ws, rows in groups.items():
        scores_newest_first = [r["overall_score"] for r in rows][:10]
        latest = rows[0]
        summary = {
            "scan_id": latest["scan_id"],
            "workspace_path": ws,
            "overall_score": latest["overall_score"],
            "status": "completed",
            "completed_at": latest.get("completed_at"),
            "repo_count": None,
            "trend_points": list(reversed(scores_newest_first)),
        }
        if len(scores_newest_first) >= 2:
            summary["delta"] = scores_newest_first[0] - scores_newest_first[1]
        workspaces.append(summary)

    workspaces.sort(key=lambda w: w.get("completed_at") or "", reverse=True)

    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspaces": workspaces,
        "active": scans["active"],
    }


def stop_all() -> dict:
    """SIGTERM every active scan whose pidfile passes verification."""
    killed: list[str] = []
    skipped: list[dict] = []
    root = scans_root()
    if not root.exists():
        return {"killed": killed, "skipped": skipped}
    for sd in sorted(root.iterdir()):
        if not sd.is_dir():
            continue
        pid_path = sd / "daemon.pid"
        status = verify_pidfile(pid_path)
        if status is PidStatus.LIVE:
            data = json.loads(pid_path.read_text())
            try:
                os.kill(data["pid"], signal.SIGTERM)
                killed.append(sd.name)
            except ProcessLookupError:
                clear_pidfile(pid_path)
        elif status in (PidStatus.STALE, PidStatus.RECYCLED):
            skipped.append({"scan_id": sd.name, "reason": status.value})
            clear_pidfile(pid_path)
    # Wait briefly for cancellations to propagate.
    time.sleep(1.0)
    return {"killed": killed, "skipped": skipped}
