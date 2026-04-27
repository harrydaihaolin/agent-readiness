"""Plugin discovery for custom checks.

Two mechanisms:
1. Local: .agent_readiness_checks/ directory at the scanned repo root. Any
   .py module in that directory is imported and its @register decorators fire.
2. Installed: Python package entry_points under group "agent_readiness.checks".
   Each entry point should be a module that exports @register-decorated functions.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_local_plugins(repo_root: Path) -> list[str]:
    """Load .agent_readiness_checks/*.py from repo root. Returns list of loaded module names."""
    plugin_dir = repo_root / ".agent_readiness_checks"
    if not plugin_dir.is_dir():
        return []
    loaded = []
    for path in sorted(plugin_dir.glob("*.py")):
        module_name = f"_ar_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
            loaded.append(module_name)
    return loaded


def load_entry_point_plugins() -> list[str]:
    """Load plugins registered via importlib.metadata entry_points."""
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return []
    eps = entry_points(group="agent_readiness.checks")
    loaded = []
    for ep in eps:
        try:
            ep.load()
            loaded.append(ep.name)
        except Exception:  # noqa: BLE001
            pass
    return loaded
