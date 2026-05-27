"""Helpers shared by the interface-precondition evaluators.

Centralised so the four (provider-must-be-documented,
provider-must-be-releasable, consumer-must-be-tested, …) family of
rules don't each reimplement the InterfaceClaim lookup against the
loaded :class:`Ontology`.
"""

from __future__ import annotations

from agent_readiness.ontology.loader import Ontology
from agent_readiness_insights_protocol.ontology.types import LifecycleState


def repos_with_interface(ont: Ontology, interface_name: str) -> set[str]:
    """Return the set of ratified Repo ids that *claim* ``interface_name``.

    Per the manifest convention, an ObjectInstance asserts interface
    satisfaction via ``spec.implements`` — a list of dicts shaped like
    :class:`~agent_readiness_insights_protocol.ontology.types.InterfaceClaim`.
    A repo "satisfies" the interface for our purposes when at least
    one of its claims targets ``interface_name`` and the claim's
    ``satisfaction`` is either ``"ratified"`` (audited) or
    ``"proposed"`` (in flight — we don't penalise pending ratification
    on the inference layer).
    """
    out: set[str] = set()
    for inst in ont.object_instances.get("Repo", []):
        if inst.lifecycle.state != LifecycleState.RATIFIED:
            continue
        repo_id = inst.metadata.get("id")
        if not repo_id:
            continue
        implements = (inst.spec or {}).get("implements") or []
        for claim in implements:
            if not isinstance(claim, dict):
                continue
            if claim.get("interface") != interface_name:
                continue
            if claim.get("satisfaction") in ("ratified", "proposed"):
                out.add(repo_id)
                break
    return out


def repos_with_link_role(
    ont: Ontology, link_type: str, role: str
) -> set[str]:
    """Return repo ids that appear in ratified ``link_type`` links as ``role``.

    ``role`` is ``"from"`` or ``"to"``. Used to ask "which repos
    provide a Protocol?", "which repos consume one?", etc., without
    duplicating the link-traversal boilerplate in every evaluator.
    """
    out: set[str] = set()
    for link in ont.link_instances.get(link_type, []):
        if link.lifecycle.state != LifecycleState.RATIFIED:
            continue
        ref = (link.spec or {}).get(role) or {}
        rid = ref.get("id")
        if rid:
            out.add(rid)
    return out


__all__ = ["repos_with_interface", "repos_with_link_role"]
