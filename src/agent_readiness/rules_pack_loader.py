"""Locate the vendored rules pack on disk.

The rules pack is vendored (not pip-installed) so it ships with the
wheel. This module handles the small dance of locating the directory
inside an installed package vs an editable checkout.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def default_rules_dir() -> Path | None:
    """Return the path to the vendored rules pack, or None if absent.

    Absence is OK — the rules pack is opt-in and a developer working on
    a checkout that hasn't run scripts/vendor_rules.sh yet should still
    be able to run agent-readiness.
    """
    try:
        traversable = files("agent_readiness").joinpath("rules_pack")
    except (ModuleNotFoundError, AttributeError):
        return None
    # Convert importlib.resources.Traversable -> Path; this works for
    # filesystem-backed packages, which is our case (no zipped wheels in
    # the wild that would need extract_to).
    try:
        path = Path(str(traversable))
    except TypeError:
        return None
    if not path.is_dir():
        return None
    return path


def vendored_manifest() -> dict[str, str] | None:
    """Read the MANIFEST file written by scripts/vendor_rules.sh."""
    rd = default_rules_dir()
    if rd is None:
        return None
    manifest_path = rd / "MANIFEST"
    if not manifest_path.is_file():
        return None
    out: dict[str, str] = {}
    for line in manifest_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"')
    return out


__all__ = ["default_rules_dir", "vendored_manifest"]
