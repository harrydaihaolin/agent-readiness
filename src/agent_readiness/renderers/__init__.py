"""Renderers turn a Report into output: terminal text or JSON.

Renderers must not mutate the Report. JSON output must not depend on
rich (or any optional dep) — the headless contract requires stable
machine-readable output without a TTY.
"""
