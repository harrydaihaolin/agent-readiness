"""Scan history: meta.json, archive rotation, retention pruning, log rotation."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from agent_readiness.live_scan.envelope import atomic_write_json


META_SCHEMA = 1
DEFAULT_RETENTION = 30
DEFAULT_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB


def read_meta(scan_dir: Path) -> dict:
    """Read meta.json or return a stub if absent."""
    p = scan_dir / "meta.json"
    if not p.exists():
        return {"schema": META_SCHEMA, "scans": []}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"schema": META_SCHEMA, "scans": []}


def register_scan(
    scan_dir: Path,
    *,
    workspace_path: str,
    workspace_hash: str,
    ts: str,
    status: str,
    overall: float | None,
) -> None:
    """Append a scan entry to meta.json (atomic write)."""
    meta = read_meta(scan_dir)
    meta.setdefault("schema", META_SCHEMA)
    meta["workspace_path"] = workspace_path
    meta["workspace_hash"] = workspace_hash
    meta.setdefault("first_seen", ts)
    meta.setdefault("scans", []).append({
        "ts": ts,
        "status": status,
        "overall": overall,
    })
    atomic_write_json(scan_dir / "meta.json", meta)


def _ts_now() -> str:
    """Filename-safe ISO timestamp (colons → dashes)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def archive_envelope(scan_dir: Path) -> str:
    """Rename live.json → archive/<ts>.json, also write latest.json copy.

    Returns the timestamp used as the archive filename.
    """
    live = scan_dir / "live.json"
    if not live.exists():
        raise FileNotFoundError(f"no live.json in {scan_dir}")
    ts = _ts_now()
    archive = scan_dir / "archive"
    archive.mkdir(exist_ok=True)
    target = archive / f"{ts}.json"
    contents = live.read_text()
    target.write_text(contents)
    (scan_dir / "latest.json").write_text(contents)
    live.unlink()
    return ts


def prune_archive(scan_dir: Path, keep: int | None = None) -> None:
    """Two-phase prune: soft-delete older archives to .trash/, hard-delete prior trash.

    ``keep`` defaults to ``AGENT_READINESS_SCAN_RETENTION`` env var or 30.
    """
    if keep is None:
        keep = int(os.environ.get("AGENT_READINESS_SCAN_RETENTION", DEFAULT_RETENTION))
    arc = scan_dir / "archive"
    trash = arc / ".trash"
    if trash.exists():
        shutil.rmtree(trash)
    if not arc.exists():
        return
    archives = sorted(
        [p for p in arc.iterdir() if p.is_file() and p.suffix == ".json"],
        key=lambda p: p.name,
    )
    if len(archives) <= keep:
        return
    trash.mkdir(exist_ok=True)
    for old in archives[:-keep]:
        old.rename(trash / old.name)


def rotate_log(log_path: Path, max_bytes: int = DEFAULT_LOG_MAX_BYTES) -> None:
    """If ``log_path`` exceeds ``max_bytes``, move to ``.1`` and truncate."""
    if not log_path.exists():
        return
    if log_path.stat().st_size <= max_bytes:
        return
    rotated = log_path.with_suffix(log_path.suffix + ".1")
    if rotated.exists():
        rotated.unlink()
    log_path.rename(rotated)
    log_path.write_text("")
