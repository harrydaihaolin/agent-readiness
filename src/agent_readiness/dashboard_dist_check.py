"""Freshness guard for the packaged dashboard ``_dashboard_dist``.

The engine and its SPA live in two repos. When the engine starts emitting
URLs for a new view (``scan-*`` advertises ``/#/onboarding/<scan_id>``) but
ships a ``_dashboard_dist`` built *before* that view existed, the dashboard
loads its chrome and renders a blank body — the router has no matching
route. This module pins that coupling: the bundled JS must contain every
route the engine hands out, or the dist is stale and must be rebuilt.
"""
from __future__ import annotations

from pathlib import Path

# Routes the engine actively links users to. Each MUST be present in the
# bundled JS or the SPA cannot render what the CLI/API advertises. Keep in
# lock-step with the URLs produced in ``cli.py`` / ``live_scan`` handlers.
REQUIRED_ROUTE_MARKERS: tuple[str, ...] = (
    "/onboarding/",
    "/workspaces/",
)

_REBUILD_HINT = "_dashboard_dist is stale — rebuild it with `make dashboard`."


def find_dist_problems(dist: Path) -> list[str]:
    """Return a list of human-readable problems with ``dist``; empty == OK."""
    dist = Path(dist)
    problems: list[str] = []

    index = dist / "index.html"
    if not index.exists():
        problems.append(f"{index} missing — run `make dashboard` first.")
        return problems

    assets = dist / "assets"
    js_files = sorted(assets.glob("*.js")) if assets.is_dir() else []
    if not js_files:
        problems.append(f"no bundled JS under {assets} — {_REBUILD_HINT}")
        return problems

    js_blob = "\n".join(f.read_text(errors="ignore") for f in js_files)
    for marker in REQUIRED_ROUTE_MARKERS:
        if marker not in js_blob:
            problems.append(
                f"bundled dashboard is missing route {marker!r} — {_REBUILD_HINT}"
            )
    return problems
