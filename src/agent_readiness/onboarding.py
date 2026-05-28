"""On-disk OnboardingState persistence (``<scan_dir>/onboarding.json``).

Atomic writes via tmp-rename. Single source of truth for the wizard's
pre-scan choices; consumed by the live_scan HTTP server's onboarding
endpoints (plan 2) and the dashboard wizard (plan 4).
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

# Re-export the protocol models so callers can import everything from
# ``agent_readiness.onboarding`` without a second import.
from agent_readiness_insights_protocol import (
    EnumerationResult,
    OnboardingClassification,
    OnboardingSelection,
    OnboardingState,
    WorkspaceType,
)

ONBOARDING_FILENAME = "onboarding.json"


def path_for(scan_id: str) -> Path:
    """Resolve the on-disk scan directory for ``scan_id``."""
    return Path.home() / ".agent-readiness" / "scans" / scan_id


def load(scan_dir: Path) -> Optional[OnboardingState]:
    """Read the OnboardingState from ``<scan_dir>/onboarding.json``.

    Returns None if the file doesn't exist. Raises ValidationError on
    malformed JSON (intentional — silent fallback would mask bugs)."""
    p = scan_dir / ONBOARDING_FILENAME
    if not p.is_file():
        return None
    return OnboardingState.model_validate_json(p.read_text())


def save(scan_dir: Path, state: OnboardingState) -> None:
    """Atomic write: dump to tmp, fsync, rename."""
    scan_dir.mkdir(parents=True, exist_ok=True)
    target = scan_dir / ONBOARDING_FILENAME

    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".onboarding.",
        suffix=".tmp",
        dir=str(scan_dir),
    )
    tmp = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(state.model_dump_json(indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        # Leave no half-baked tmp file behind.
        if tmp.exists():
            tmp.unlink()
        raise


def commit_selection(
    scan_dir: Path,
    *,
    type: WorkspaceType,
    selected_paths: list[str],
    committed_at: datetime,
) -> OnboardingState:
    """Atomically update ``onboarding.json`` with a new selection.

    Increments ``selection.revision``: 1 on first commit, +1 each time
    Reconfigure is called. Also updates ``committed_type`` so subsequent
    reads see the user's chosen type (which may differ from the type the
    tool originally committed via 'Switch type' in the wizard)."""
    current = load(scan_dir)
    if current is None:
        raise FileNotFoundError(
            f"no onboarding.json in {scan_dir}; cannot commit selection "
            "without an existing enumeration"
        )
    next_revision = (current.selection.revision + 1) if current.selection else 1
    updated = current.model_copy(update={
        "committed_type": type,
        "selection": OnboardingSelection(
            type=type,
            selected_paths=selected_paths,
            revision=next_revision,
            committed_at=committed_at,
        ),
    })
    save(scan_dir, updated)
    return updated


__all__ = [
    "ONBOARDING_FILENAME",
    "path_for",
    "load",
    "save",
    "commit_selection",
    # Re-exports for ergonomic imports.
    "EnumerationResult",
    "OnboardingClassification",
    "OnboardingSelection",
    "OnboardingState",
    "WorkspaceType",
]
