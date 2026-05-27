"""Public surface of the ontology reasoning layer (Bundle C).

Importing this package registers every evaluator under
:mod:`.evaluators` into the engine's REGISTRY, so callers can
``from agent_readiness.ontology.reasoning import run_inference`` and
get a fully-populated chainer with no extra wiring.

See :mod:`agent_readiness.ontology.reasoning.engine` for the
inference engine itself; see the individual modules under
:mod:`.evaluators` for each rule's logic; see
``agent-readiness-research/docs/superpowers/plans/2026-05-26-bundle-c-ontology-reasoning.md``
for the rollout plan and the six v1 rules' rationale.
"""

from __future__ import annotations

from agent_readiness.ontology.reasoning.engine import (
    REGISTRY,
    DerivedViolation,
    Evaluator,
    register,
    run_inference,
    violation_to_dict,
)
from agent_readiness.ontology.reasoning import evaluators  # noqa: F401 -- registers all evaluators

__all__ = [
    "DerivedViolation",
    "Evaluator",
    "REGISTRY",
    "register",
    "run_inference",
    "violation_to_dict",
]
