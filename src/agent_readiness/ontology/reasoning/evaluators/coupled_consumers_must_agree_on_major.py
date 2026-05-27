"""Inference: coupled consumers must agree on a Protocol's major version.

This is the rule that articulates the value prop of the inference
layer most directly: it would have caught the cross-repo pin skew
between ``agent-readiness-ontology-mcp`` (still pinned at protocol
``<0.8.0`` at the time Bundle C was authored) and its sibling
``agent-readiness-mcp`` (already on ``>=0.9.0,<0.10.0``) *before*
PR C-3 of Bundle C was written by hand.

The rule: if Repo ``A dependsOn Repo B`` and both repos
``consumesProtocol`` the same Protocol (modulo version pin), then
the major (X) component of their consumed versions must agree. A
disagreement means A pulls in B at runtime expecting one major and
B is actually expecting another — undefined behaviour territory.

Versions are parsed loosely: anything before the first ``.`` after
the ``@`` is the major. Non-numeric "0" majors (pre-1.0 packages)
are still compared as strings — at <1.0 the *minor* is treated as
the major-equivalent (a 0.8 → 0.9 transition typically breaks). We
keep the parser one-liner and rely on the rule emitting only when
the *string before the second dot* disagrees, which captures both
the 1.x ↔ 2.x case and the 0.8 ↔ 0.9 case the umbrella actually
has.
"""

from __future__ import annotations

from collections import defaultdict

from agent_readiness.ontology.loader import Ontology
from agent_readiness.ontology.reasoning.engine import (
    DerivedViolation,
    register,
)
from agent_readiness_insights_protocol.ontology.types import LifecycleState

_RULE_ID = "ontology.inference.coupled_consumers_must_agree_on_major"


def _split_pin(target_id: str) -> tuple[str, str] | None:
    """Return ``(protocol_name, "X.Y")`` from a ``<name>@<X.Y.Z>`` id.

    Truncated to two components so 0.x pre-releases (where the
    minor is the practical breaking-change axis) get compared
    correctly alongside post-1.0 majors. Returns ``None`` when the
    id has no ``@`` or no version segment we can split.
    """
    if "@" not in target_id:
        return None
    name, _, version = target_id.partition("@")
    if not version:
        return None
    parts = version.split(".")
    if len(parts) < 2:
        return (name, parts[0])
    return (name, f"{parts[0]}.{parts[1]}")


def _ratified_consumes(ont: Ontology) -> dict[str, list[tuple[str, str]]]:
    """Return ``{repo_id: [(protocol_name, "X.Y"), ...]}``."""
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for link in ont.link_instances.get("consumesProtocol", []):
        if link.lifecycle.state != LifecycleState.RATIFIED:
            continue
        spec = link.spec or {}
        repo_id = (spec.get("from") or {}).get("id")
        target_id = (spec.get("to") or {}).get("id")
        if not repo_id or not target_id:
            continue
        pin = _split_pin(target_id)
        if pin is None:
            continue
        out[repo_id].append(pin)
    return out


def _ratified_depends_pairs(ont: Ontology) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for link in ont.link_instances.get("dependsOn", []):
        if link.lifecycle.state != LifecycleState.RATIFIED:
            continue
        spec = link.spec or {}
        frm = (spec.get("from") or {}).get("id")
        to = (spec.get("to") or {}).get("id")
        if frm and to:
            pairs.append((frm, to))
    return pairs


@register(_RULE_ID)
def evaluate(ont: Ontology) -> list[DerivedViolation]:
    consumes = _ratified_consumes(ont)
    pairs = _ratified_depends_pairs(ont)
    out: list[DerivedViolation] = []
    seen: set[tuple[str, str, str]] = set()
    for a, b in pairs:
        a_pins = {name: ver for name, ver in consumes.get(a, [])}
        b_pins = {name: ver for name, ver in consumes.get(b, [])}
        for proto_name, a_ver in a_pins.items():
            b_ver = b_pins.get(proto_name)
            if b_ver is None:
                continue
            if a_ver == b_ver:
                continue
            key = (proto_name, *sorted([f"{a}@{a_ver}", f"{b}@{b_ver}"]))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                DerivedViolation(
                    rule_id=_RULE_ID,
                    detail=(
                        f"Coupled consumers disagree on Protocol "
                        f"{proto_name!r}: {a!r} consumes "
                        f"{proto_name}@{a_ver} but {b!r} (which {a!r} "
                        f"dependsOn) consumes {proto_name}@{b_ver} — "
                        "transitively-coupled repos must agree on the "
                        "consumed major"
                    ),
                    severity="error",
                )
            )
    return out
