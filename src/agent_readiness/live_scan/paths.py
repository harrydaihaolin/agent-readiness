"""Workspace hash + on-disk scan-dir resolution.

``workspace_hash(path)`` produces a stable, human-readable directory name
for a workspace based on its resolved absolute path. The basename gives
the prefix (debugging affordance); a SHA1 suffix avoids collisions across
workspaces that happen to share a basename.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def scans_root() -> Path:
    """Root directory for all on-disk scan state."""
    return Path(os.path.expanduser("~")) / ".agent-readiness" / "scans"


def workspace_hash(path: Path) -> str:
    """Deterministic, human-readable directory name for a workspace.

    Format: ``<basename>-<sha1[:6]>``. Resolves the path first so symlinks
    and relative paths collapse to the same identity.
    """
    resolved = Path(path).expanduser().resolve()
    suffix = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:6]
    return f"{resolved.name}-{suffix}"


def scan_dir(path: Path) -> Path:
    """Per-workspace scan directory under ``scans_root()``."""
    return scans_root() / workspace_hash(path)
