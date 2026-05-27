"""Side-effect-only package: importing it registers every evaluator.

Each module under this package defines one ``evaluate`` function
decorated with ``@register("ontology.inference.<name>")`` from
:mod:`agent_readiness.ontology.reasoning.engine`. Listing them in
the import block below is what populates the engine's REGISTRY at
import time; downstream callers (the CLI subcommand, the
``ontology_inference`` private matcher, the
``reason_over_ontology`` MCP tool) just call ``run_inference`` and
trust that the registry is full.

Adding a new evaluator: drop a module here, add it to the import
list. The side-effect pattern mirrors
``agent_readiness.rules_eval.private_matchers``.
"""

from __future__ import annotations

from . import (  # noqa: F401  -- import for side effect (registration)
    acyclic_dependsOn,
    consumer_must_pin_protocol_version,
    coupled_consumers_must_agree_on_major,
    irreflexive_dependsOn,
    protocol_provider_must_be_releasable,
    provider_must_be_documented,
)

__all__: list[str] = []
