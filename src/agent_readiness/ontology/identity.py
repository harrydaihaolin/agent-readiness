"""Render an ObjectType.id_template against an ObjectInstance's properties.

The template DSL is intentionally tiny: ``{{ var }}`` substitution with
arbitrary inner whitespace, no filters or expressions. Missing properties
raise ``KeyError``; non-string values are coerced via ``str()``.

This is the renderer §1.1 of `2026-05-25-ontology-improvement-plan.md`
requires the validator to enforce on every instance load.
"""
from __future__ import annotations

import re
from typing import Any

_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def compute_pk(template: str, properties: dict[str, Any]) -> str:
    """Render `template` against `properties`. Raises KeyError on missing var."""

    def _sub(match: re.Match[str]) -> str:
        var = match.group(1)
        if var not in properties:
            raise KeyError(var)
        return str(properties[var])

    return _VAR_RE.sub(_sub, template)
