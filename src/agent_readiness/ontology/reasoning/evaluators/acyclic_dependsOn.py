"""Inference: the ``dependsOn`` graph must be acyclic.

The ``dependsOn`` LinkType declares ``axioms.acyclic: true`` (see
``agent-readiness-manifest/ontology/linkTypes/dependsOn.yaml``).
That axiom is what makes the umbrella's release-order machinery work
— ``compute_publish_order`` assumes a DAG and falls into infinite
recursion on a cycle. This evaluator walks the ratified-only edge
set and emits one violation per detected back-edge cycle.

Algorithm: iterative DFS with a recursion stack. Each cycle is
reported once, with the participants in traversal order. On the
umbrella today (~7 dependsOn links) the search is O(V+E) and
trivially fast.
"""

from __future__ import annotations

from agent_readiness.ontology.loader import Ontology
from agent_readiness.ontology.reasoning.engine import (
    DerivedViolation,
    register,
)
from agent_readiness_insights_protocol.ontology.types import LifecycleState

_RULE_ID = "ontology.inference.acyclic_dependsOn"


def _ratified_edges(ont: Ontology) -> dict[str, list[str]]:
    """Return ``{from_id: [to_id, ...]}`` for ratified ``dependsOn`` links.

    Self-loops are deliberately excluded — they violate the
    *irreflexive* axiom and are reported by
    ``irreflexive_dependsOn``. Including them here would double-report
    the same atom under two rule ids, which is noisy and confuses
    triage (the operator sees two findings for one bug).
    """
    edges: dict[str, list[str]] = {}
    for link in ont.link_instances.get("dependsOn", []):
        if link.lifecycle.state != LifecycleState.RATIFIED:
            continue
        spec = link.spec or {}
        frm = (spec.get("from") or {}).get("id")
        to = (spec.get("to") or {}).get("id")
        if not frm or not to or frm == to:
            continue
        edges.setdefault(frm, []).append(to)
    return edges


def _find_cycles(edges: dict[str, list[str]]) -> list[list[str]]:
    """Iterative DFS; returns one cycle per back-edge discovered."""
    cycles: list[list[str]] = []
    visited: set[str] = set()
    nodes = list(edges.keys()) + [
        n for targets in edges.values() for n in targets if n not in edges
    ]
    for start in nodes:
        if start in visited:
            continue
        # path stores the active DFS chain; on_stack mirrors it for O(1) lookup.
        stack: list[tuple[str, list[str]]] = [(start, list(edges.get(start, [])))]
        path: list[str] = [start]
        on_stack: set[str] = {start}
        while stack:
            _, remaining = stack[-1]
            if not remaining:
                done = path.pop()
                on_stack.discard(done)
                stack.pop()
                visited.add(done)
                continue
            nxt = remaining.pop()
            if nxt in on_stack:
                cycle_start = path.index(nxt)
                cycles.append(path[cycle_start:] + [nxt])
                continue
            if nxt in visited:
                continue
            path.append(nxt)
            on_stack.add(nxt)
            stack.append((nxt, list(edges.get(nxt, []))))
    return cycles


@register(_RULE_ID)
def evaluate(ont: Ontology) -> list[DerivedViolation]:
    edges = _ratified_edges(ont)
    out: list[DerivedViolation] = []
    for cycle in _find_cycles(edges):
        chain = " → ".join(cycle)
        out.append(
            DerivedViolation(
                rule_id=_RULE_ID,
                detail=f"Cycle in dependsOn graph: {chain}",
                severity="error",
            )
        )
    return out
