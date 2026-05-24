"""query — tiny grammar over the loaded ontology graph.

Supported forms (v1):
- count(<ObjectType>)              → int
- list(<ObjectType>)               → list[str] (atom ids)
- links(<ObjectType>:<id>)         → list[dict] (link instances touching that atom)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_readiness.ontology.loader import load_ontology

_COUNT = re.compile(r"^count\(\s*(?P<t>\w+)\s*\)$")
_LIST = re.compile(r"^list\(\s*(?P<t>\w+)\s*\)$")
_LINKS = re.compile(r"^links\(\s*(?P<t>\w+)\s*:\s*(?P<id>[\w\-./@]+)\s*\)$")


def query_ontology(root: Path, expr: str) -> Any:
    ont = load_ontology(root)

    m = _COUNT.match(expr)
    if m:
        return len(ont.object_instances.get(m.group("t"), []))

    m = _LIST.match(expr)
    if m:
        return [inst.metadata.get("id") for inst in ont.object_instances.get(m.group("t"), [])]

    m = _LINKS.match(expr)
    if m:
        atom_id = m.group("id")
        hits: list[dict] = []
        for type_name, links in ont.link_instances.items():
            for link in links:
                spec = link.spec or {}
                frm = (spec.get("from") or {}).get("id")
                to_ = (spec.get("to") or {}).get("id")
                if frm == atom_id or to_ == atom_id:
                    hits.append({
                        "link_type": type_name,
                        "id": link.metadata.get("id"),
                        "from": spec.get("from"),
                        "to": spec.get("to"),
                    })
        return hits

    raise ValueError(
        f"Unsupported query: {expr!r}. Try count(<Type>) | list(<Type>) | links(<Type>:<id>)"
    )
