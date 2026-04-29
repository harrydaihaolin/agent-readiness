"""Locate the rules pack via the installed ``agent_readiness_rules`` pkg.

Pre-Q1 the rules pack was vendored under
``src/agent_readiness/rules_pack/`` and refreshed by
``scripts/vendor_rules.sh``. Q1 phase 4 swaps that for a normal pip
dependency: the ``agent-readiness-rules`` distribution ships an
``agent_readiness_rules`` Python package that exposes the YAMLs as
package data. We resolve the directory through it.

Absence is still OK — a developer working on a checkout that hasn't
installed ``agent-readiness-rules`` yet should still be able to import
``agent_readiness`` without a hard crash. The CLI surfaces a clear
``error: no rules loaded`` message in that case.
"""

from __future__ import annotations

from pathlib import Path


def default_rules_dir() -> Path | None:
    """Return the path to the installed rules pack, or None if absent.

    Resolves the ``agent_readiness_rules.rules_dir()`` helper if the
    package is installed; returns None otherwise.
    """
    try:
        from agent_readiness_rules import rules_dir as _rules_dir
    except ImportError:
        return None
    try:
        path = _rules_dir()
    except FileNotFoundError:
        return None
    if not path.is_dir():
        return None
    return path


def vendored_manifest() -> dict[str, str] | None:
    """Read ``manifest.toml`` from the installed rules pack.

    Returns a dict of the top-level scalar fields (rules_version,
    pack_version, …) so dashboards can show what version of the pack
    is in play. Returns None if the pack is absent or the manifest is
    missing.
    """
    try:
        from agent_readiness_rules import manifest_path
    except ImportError:
        return None
    try:
        path = manifest_path()
    except FileNotFoundError:
        return None
    if not path.is_file():
        return None
    try:
        import tomllib
    except ImportError:  # pragma: no cover - python < 3.11
        return None
    data = tomllib.loads(path.read_text())
    out: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(v, (str, int, float, bool)):
            out[k] = str(v)
    return out


__all__ = ["default_rules_dir", "vendored_manifest"]
