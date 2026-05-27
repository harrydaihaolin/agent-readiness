"""Inference: any Repo providing a Protocol must claim ``Documented``.

Why this is an *inference* rule and not a per-file scan: the
provider-Documented coupling is not visible from inside a single
repo. It only emerges when you cross-reference the ``providesProtocol``
edge with the provider Repo's InterfaceClaim list — exactly the kind
of fact the forward chainer is meant to derive.

Consumers pin to a specific Protocol version (``X@1.2.3``); if the
provider's docs are stale or absent, the consumer's pin documents a
contract the provider can't explain. Flag the provider as soon as
the docs slip below claim.
"""

from __future__ import annotations

from agent_readiness.ontology.loader import Ontology
from agent_readiness.ontology.reasoning.engine import (
    DerivedViolation,
    register,
)
from agent_readiness.ontology.reasoning.evaluators._iface_helpers import (
    repos_with_interface,
    repos_with_link_role,
)

_RULE_ID = "ontology.inference.provider_must_be_documented"


@register(_RULE_ID)
def evaluate(ont: Ontology) -> list[DerivedViolation]:
    providers = repos_with_link_role(ont, "providesProtocol", "from")
    documented = repos_with_interface(ont, "Documented")
    missing = sorted(providers - documented)
    return [
        DerivedViolation(
            rule_id=_RULE_ID,
            subject_id=repo_id,
            detail=(
                f"Repo {repo_id!r} provides a Protocol but does not claim "
                "the Documented interface — consumers pin to its release "
                "without a contract reference"
            ),
            severity="warn",
        )
        for repo_id in missing
    ]
