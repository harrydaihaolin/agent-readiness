from __future__ import annotations

from agent_readiness.ontology.bootstrap.init import InitReport, init_ontology
from agent_readiness.ontology.bootstrap.propose_interfaces import propose_interface_claims
from agent_readiness.ontology.bootstrap.propose_links import propose_link_instances
from agent_readiness.ontology.bootstrap.propose_objects import propose_object_instances

__all__ = [
    "InitReport",
    "init_ontology",
    "propose_object_instances",
    "propose_link_instances",
    "propose_interface_claims",
]
