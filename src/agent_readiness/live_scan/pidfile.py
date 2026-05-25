"""PID file with start-time stamp.

``daemon.pid`` is a JSON file:

    { "pid": int, "started_at": float (epoch), "scan_id": str }

``verify_pidfile`` checks both that the PID is alive AND that the process's
reported start time matches what we recorded. Mismatch means the PID was
recycled — abort any subsequent SIGTERM.
"""
from __future__ import annotations

import enum
import json
import os
from pathlib import Path

import psutil

from agent_readiness.live_scan.envelope import atomic_write_json


class PidStatus(enum.Enum):
    LIVE = "live"           # PID alive + start-time matches
    RECYCLED = "recycled"   # PID alive but a different process
    STALE = "stale"         # PID dead
    MISSING = "missing"     # No pid file present


def write_pidfile(path: Path, scan_id: str) -> None:
    """Write the current process's PID + start time to ``path``."""
    proc = psutil.Process(os.getpid())
    atomic_write_json(path, {
        "pid": os.getpid(),
        "started_at": proc.create_time(),
        "scan_id": scan_id,
    })


def verify_pidfile(path: Path) -> PidStatus:
    """Classify the pidfile against the OS's view of the world."""
    if not path.exists():
        return PidStatus.MISSING
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return PidStatus.STALE
    pid = data.get("pid")
    started_at = data.get("started_at")
    if pid is None or started_at is None:
        return PidStatus.STALE
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return PidStatus.STALE
    # Compare start time within a small tolerance (psutil and JSON round-trip
    # can lose precision below 1ms).
    if abs(proc.create_time() - float(started_at)) > 0.01:
        return PidStatus.RECYCLED
    return PidStatus.LIVE


def clear_pidfile(path: Path) -> None:
    """Remove the pidfile if it exists. Idempotent."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
