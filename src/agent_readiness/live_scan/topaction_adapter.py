"""Adapter: bridge the dashboard's ``POST /api/scans/<id>/topaction/apply``
to the existing :func:`agent_readiness.apply_action.apply_top_action`.

Reads the in-flight or most-recently-completed scan envelope from disk
to find the workspace's pinned ``top_action``, then applies it against
the workspace path the dashboard server was bound to.

The diff endpoint (``GET /api/scans/<id>/topaction/diff``) is not
implemented yet — the spec lists it as a UI nicety that can ship after
the main wiring lands. Until then the API handler returns 501.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_readiness.live_scan.paths import scan_dir


def _load_latest_envelope(workspace_path: Path) -> dict[str, Any] | None:
    """Return the most recent envelope dict for ``workspace_path``.

    Prefers ``live.json`` (in-progress); falls back to ``latest.json``.
    Returns ``None`` if neither is present or readable.
    """
    sd = scan_dir(workspace_path)
    for name in ("live.json", "latest.json"):
        p = sd / name
        if not p.exists():
            continue
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return None


def apply_top_action_to_path(
    workspace_path: Path,
    *,
    run_verify: bool = True,
) -> dict[str, Any]:
    """Apply the pinned top_action for ``workspace_path``.

    Returns a dict matching the dashboard's API contract:
    ``{ applied, verified, output }``. The ``output`` field carries
    a multi-line summary suitable for showing in the dashboard's
    apply-result toast.
    """
    envelope = _load_latest_envelope(workspace_path)
    if envelope is None:
        return {
            "applied": False,
            "verified": False,
            "output": "no scan envelope found on disk",
        }
    top_action = envelope.get("top_action")
    if top_action is None:
        return {
            "applied": False,
            "verified": False,
            "output": "no top_action pinned",
        }

    # The scan envelope's top_action is per-workspace; for monorepos /
    # multi-repo, ``apply_top_action`` is per-repo. v1 dashboard targets
    # single-workspace flows where the workspace_path IS the repo to
    # apply against. For deeper multi-repo apply support we'll route
    # per-child via a future apply_top_action_to_child().
    from agent_readiness.apply_action import apply_top_action as _apply
    result = _apply(top_action, workspace_path, run_verify=run_verify)
    return {
        "applied": bool(result.applied),
        "verified": bool(result.verified),
        "output": (
            f"applied={result.applied} verified={result.verified}\n"
            + (result.skipped_reason or "")
            + ("\n" + (result.verify_output or "") if result.verify_output else "")
        ),
    }
