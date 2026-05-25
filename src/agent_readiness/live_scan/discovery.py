"""Cross-workspace enumeration: ``list_scans`` + ``stop_all``."""
from __future__ import annotations

import json
import os
import signal
import time
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
