"""Inference: any Repo providing a Protocol must claim ``Releasable``.

Same shape as ``provider_must_be_documented`` but for the Releasable
interface: if a provider can't cut versioned releases, downstream
``consumesProtocol p@X.Y.Z`` pins reference fiction. The umbrella's
release-cascade Intent depends on the provider being able to tag,
build, and publish; the Releasable claim is the audited token of
that capability.

Distinct rule (rather than a parameterised one) so its YAML can
carry a per-interface fix_hint pointing at the Releasable proof.
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

_RULE_ID = "ontology.inference.protocol_provider_must_be_releasable"


@register(_RULE_ID)
def evaluate(ont: Ontology) -> list[DerivedViolation]:
    providers = repos_with_link_role(ont, "providesProtocol", "from")
    releasable = repos_with_interface(ont, "Releasable")
    missing = sorted(providers - releasable)
    return [
        DerivedViolation(
            rule_id=_RULE_ID,
            subject_id=repo_id,
            detail=(
                f"Repo {repo_id!r} provides a Protocol but does not claim "
                "the Releasable interface — consumers cannot pin a "
                "release because the provider has no audited release "
                "capability"
            ),
            severity="warn",
        )
        for repo_id in missing
    ]
