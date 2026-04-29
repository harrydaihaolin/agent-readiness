"""Plugin discovery for downstream extension code.

Two mechanisms:

1. Local: ``.agent_readiness_checks/`` directory at the scanned repo
   root. Any ``.py`` module in that directory is imported.
2. Installed: Python package entry_points under group
   ``agent_readiness.matchers`` (preferred) or ``agent_readiness.checks``
   (legacy alias, kept working until 2.0).

Post-Q1, plugins extend agent-readiness by calling
:func:`agent_readiness.rules_eval.register_private_matcher` at import
time and shipping a YAML rules directory the user points at via
``--rules-dir``. The plugin loader itself is intentionally
mechanism-agnostic — it just imports modules and lets them do whatever
they want at import time.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Order matters: the new group is preferred but we also load anything
# registered under the historical group so existing third-party
# packages don't break on the cutover.
_ENTRY_POINT_GROUPS: tuple[str, ...] = (
    "agent_readiness.matchers",
    "agent_readiness.checks",
)


def load_local_plugins(repo_root: Path) -> list[str]:
    """Load .agent_readiness_checks/*.py from repo root.

    Returns the list of loaded module names. The directory name is
    intentionally still ``.agent_readiness_checks`` for backward
    compatibility with existing on-disk plugins.
    """
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
    """Load plugins registered via importlib.metadata entry_points.

    Both the preferred group (``agent_readiness.matchers``) and the
    legacy group (``agent_readiness.checks``) are loaded; failures in
    individual plugins are swallowed so one broken third-party package
    doesn't take down the scan.
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return []
    loaded: list[str] = []
    for group in _ENTRY_POINT_GROUPS:
        eps = entry_points(group=group)
        for ep in eps:
            try:
                ep.load()
                loaded.append(ep.name)
            except Exception:  # noqa: BLE001
                pass
    return loaded
