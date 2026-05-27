"""Shared fixture helpers for the reasoning evaluator tests.

The forward chainer in :mod:`agent_readiness.ontology.reasoning`
operates over a loaded :class:`~agent_readiness.ontology.loader.Ontology`
dataclass. Each evaluator test wants a small in-memory ``Ontology``
shaped exactly right to exercise one rule. Building those by hand
(``ObjectInstance(apiVersion=..., kind=..., metadata=..., spec=...,
lifecycle=Lifecycle(...))`` per row) gets noisy fast — these helpers
trim that down to one-line constructors with sensible defaults.
"""

from __future__ import annotations

from typing import Any

from agent_readiness.ontology.loader import Ontology
from agent_readiness_insights_protocol.ontology.types import (
    LifecycleState,
    LinkInstance,
    ObjectInstance,
)


def _ratified_lifecycle() -> dict[str, Any]:
    return {
        "state": LifecycleState.RATIFIED,
        "proposed_by": "test",
        "proposed_at": "2026-05-26T00:00:00+00:00",
        "confidence": 1.0,
        "markers": [],
        "ratified_by": "test",
        "ratified_at": "2026-05-26T00:00:00+00:00",
    }


def make_object(
    object_id: str,
    object_type: str = "Repo",
    *,
    implements: list[dict[str, Any]] | None = None,
    properties: dict[str, Any] | None = None,
) -> ObjectInstance:
    spec: dict[str, Any] = {"properties": properties or {}}
    if implements is not None:
        spec["implements"] = implements
    return ObjectInstance(
        apiVersion="agent-readiness.io/v1",
        kind="ObjectInstance",
        metadata={"object_type": object_type, "id": object_id},
        spec=spec,
        lifecycle=_ratified_lifecycle(),
    )


def make_link(
    link_type: str,
    from_id: str,
    to_id: str,
    *,
    from_type: str = "Repo",
    to_type: str = "Repo",
    link_id: str | None = None,
) -> LinkInstance:
    link_id = link_id or f"{from_id}--{link_type}--{to_id}"
    return LinkInstance(
        apiVersion="agent-readiness.io/v1",
        kind="LinkInstance",
        metadata={"link_type": link_type, "id": link_id},
        spec={
            "from": {"object_type": from_type, "id": from_id},
            "to": {"object_type": to_type, "id": to_id},
        },
        lifecycle=_ratified_lifecycle(),
    )


def make_iface_claim(
    interface: str, satisfaction: str = "ratified"
) -> dict[str, Any]:
    return {
        "interface": interface,
        "satisfaction": satisfaction,
        "last_checked": "2026-05-26T00:00:00+00:00",
        "proof_refs": [],
    }


def make_ontology(
    *,
    objects: list[ObjectInstance] | None = None,
    links: list[LinkInstance] | None = None,
) -> Ontology:
    ont = Ontology()
    for obj in objects or []:
        otype = obj.metadata.get("object_type") or "Repo"
        ont.object_instances.setdefault(otype, []).append(obj)
    for link in links or []:
        ltype = link.metadata.get("link_type")
        if ltype:
            ont.link_instances.setdefault(ltype, []).append(link)
    return ont
