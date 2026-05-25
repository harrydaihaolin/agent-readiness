"""Atomic envelope writes + envelope mutation helpers.

``atomic_write_json`` is the single chokepoint for any JSON the dashboard
might be polling — write to ``.tmp``, then ``os.replace`` to swap. POSIX
guarantees the swap is atomic from the reader's perspective.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: Any) -> None:
    """Atomically write ``data`` as JSON to ``path``.

    POSIX-only — relies on ``os.replace`` atomicity. The ``.tmp`` sibling
    is removed if the swap fails, so a crashed write never leaves debris.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, default=str))
        os.replace(tmp, path)
    except OSError:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_envelope(workspace_path: Path, total_children: int) -> dict:
    """Build a fresh in_progress envelope."""
    return {
        "schema": 1,
        "status": "in_progress",
        "progress": {
            "completed": 0,
            "total": total_children,
            "in_flight": [],
        },
        "started_at": _iso_now(),
        "completed_at": None,
        "repo_path": str(Path(workspace_path).expanduser().resolve()),
        "overall_score": None,
        "pillar_scores": {},
        "children": [],
        "coordination_findings": [],
        "top_action": None,
        "stats": {
            "scan_duration_ms": None,
            "children_failed_paths": [],
        },
        "safety_caps_applied": [],
    }


def set_in_flight(envelope: dict, paths: list[Path]) -> None:
    """Replace the in_flight list. v1 puts 0–1 paths; Spec 2 may put N."""
    envelope["progress"]["in_flight"] = [str(p) for p in paths]


def add_completed_child(envelope: dict, child_dict: dict) -> None:
    """Append a completed child and bump the completed counter."""
    envelope["children"].append(child_dict)
    envelope["progress"]["completed"] += 1
    cpath = child_dict.get("path")
    envelope["progress"]["in_flight"] = [
        p for p in envelope["progress"]["in_flight"] if p != cpath
    ]


def set_status(envelope: dict, status: str) -> None:
    """Set envelope status. Terminal statuses stamp completed_at."""
    envelope["status"] = status
    if status in ("completed", "failed", "cancelled"):
        envelope["completed_at"] = _iso_now()


def write_envelope(scan_dir: Path, envelope: dict) -> None:
    """Atomically write the envelope to ``<scan_dir>/live.json``."""
    atomic_write_json(scan_dir / "live.json", envelope)
