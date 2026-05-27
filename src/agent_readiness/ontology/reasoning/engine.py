"""Hand-rolled forward chainer over the workspace ontology graph.

Bundle C of the 2026-05-26 ontology-driven-agent design. Where the
existing :mod:`agent_readiness.ontology` modules *load*, *query*, and
*mutate* the graph, this module **derives** new facts from it —
specifically, violations of cross-cutting invariants that no single
file scan can express (cycles, transitive coupling, interface
preconditions). Each derivation is implemented as a small evaluator
function registered via :func:`register`; the engine's
:func:`run_inference` iterates the registry, calls each evaluator
against a loaded :class:`~agent_readiness.ontology.loader.Ontology`,
and returns a flat list of :class:`DerivedViolation`.

Design rationale: with N≈30 instances in the umbrella manifest, a
forward chainer in pure Python is simpler, more reviewable, and
deterministic — none of the surface area of a Datalog dep (rejected
in the 2026-05-26 brainstorm). The pluggable evaluator pattern keeps
each rule's logic colocated with its YAML metadata in
``agent-readiness-rules`` (one evaluator ↔ one rule) and matches the
existing ``private_matchers/`` shape readers already know.

The engine itself is intentionally trivial — fewer than 50 lines of
glue. The interesting code lives in :mod:`.evaluators`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from agent_readiness.ontology.loader import Ontology

Evaluator = Callable[[Ontology], list["DerivedViolation"]]


@dataclass(frozen=True)
class DerivedViolation:
    """A single derived fact representing an invariant violation.

    Emitted by an evaluator; consumed by the ``ontology_inference``
    private matcher (which turns each violation into a scan
    :class:`~agent_readiness_insights_protocol.models.Finding`) and by
    the ``agent-readiness ontology reason`` CLI / the
    ``reason_over_ontology`` MCP tool (which serialise the list to
    JSON for agent consumption).

    Fields:
        rule_id: The full inference rule id (e.g.
            ``ontology.inference.acyclic_dependsOn``). Matches the
            corresponding YAML rule's ``id`` in ``agent-readiness-rules``.
        subject_id: Optional ontology atom id the violation is about
            (an ObjectInstance or LinkInstance id). ``None`` for
            graph-wide violations like cycles (where ``detail``
            enumerates the participants).
        detail: One-sentence human-readable description; surfaces as
            the scan finding's message.
        severity: ``"warn"`` (default) or ``"error"``. Mirrors the
            corresponding YAML rule's ``severity`` so the CLI / MCP
            envelope can short-circuit without re-reading the rule
            file.
    """

    rule_id: str
    detail: str
    subject_id: str | None = None
    severity: str = "warn"


@dataclass
class _Registry:
    """Module-level evaluator registry.

    Wrapped in a dataclass (rather than a bare dict) so tests can
    snapshot/restore it without monkey-patching module globals.
    """

    evaluators: dict[str, Evaluator] = field(default_factory=dict)


REGISTRY = _Registry()


def register(rule_id: str) -> Callable[[Evaluator], Evaluator]:
    """Decorator that registers an evaluator under ``rule_id``.

    Usage::

        @register("ontology.inference.acyclic_dependsOn")
        def evaluate(ont: Ontology) -> list[DerivedViolation]:
            ...

    Re-registration is rejected so duplicate rule ids surface at
    import time (the registry is imported eagerly by
    :mod:`agent_readiness.ontology.reasoning`).
    """

    def _decorator(fn: Evaluator) -> Evaluator:
        if rule_id in REGISTRY.evaluators:
            raise ValueError(
                f"inference rule {rule_id!r} already registered "
                f"(existing: {REGISTRY.evaluators[rule_id].__module__})"
            )
        REGISTRY.evaluators[rule_id] = fn
        return fn

    return _decorator


def run_inference(
    ont: Ontology, rule_filter: str | None = None
) -> list[DerivedViolation]:
    """Run registered evaluators against ``ont``; return derived violations.

    When ``rule_filter`` is set, only the evaluator registered under
    that exact rule_id runs (used by the per-rule CLI / private
    matcher path). When ``rule_filter`` is ``None``, every registered
    evaluator runs and results are concatenated.

    Order across rules is the registration order (insertion order of
    the underlying dict); order within a rule is the evaluator's
    return order. Both are stable so snapshot tests don't flake.

    Evaluator exceptions are NOT caught — a buggy evaluator should
    fail loudly during development. Production scans are protected by
    the calling private matcher's own error handling.
    """

    if rule_filter is not None:
        fn = REGISTRY.evaluators.get(rule_filter)
        if fn is None:
            return []
        return list(fn(ont))

    out: list[DerivedViolation] = []
    for fn in REGISTRY.evaluators.values():
        out.extend(fn(ont))
    return out


def violation_to_dict(v: DerivedViolation) -> dict[str, Any]:
    """Helper for CLI / MCP JSON envelopes — :func:`dataclasses.asdict`
    drops ``None``-valued fields for a tighter wire format."""
    return {k: val for k, val in asdict(v).items() if val is not None}


__all__ = [
    "DerivedViolation",
    "Evaluator",
    "REGISTRY",
    "register",
    "run_inference",
    "violation_to_dict",
]
