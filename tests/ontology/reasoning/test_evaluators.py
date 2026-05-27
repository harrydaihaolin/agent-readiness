"""Per-evaluator tests for the six v1 inference rules.

Each rule has a positive (rule fires when expected) and negative
(rule stays silent on a well-formed graph) case. Where the rule
has multiple firing shapes (e.g. cycle vs self-loop), there's one
test per shape.
"""

from __future__ import annotations

from agent_readiness.ontology.reasoning import run_inference

from .conftest import (
    make_iface_claim,
    make_link,
    make_object,
    make_ontology,
)

# ---------- acyclic_dependsOn -------------------------------------------------


def test_acyclic_dependsOn_no_cycle_no_violation() -> None:
    ont = make_ontology(
        links=[
            make_link("dependsOn", "a", "b"),
            make_link("dependsOn", "b", "c"),
        ],
    )
    out = run_inference(ont, rule_filter="ontology.inference.acyclic_dependsOn")
    assert out == []


def test_acyclic_dependsOn_two_node_cycle_fires_once() -> None:
    ont = make_ontology(
        links=[
            make_link("dependsOn", "a", "b"),
            make_link("dependsOn", "b", "a"),
        ],
    )
    out = run_inference(ont, rule_filter="ontology.inference.acyclic_dependsOn")
    assert len(out) == 1
    assert "a" in out[0].detail and "b" in out[0].detail
    assert out[0].severity == "error"


def test_acyclic_dependsOn_three_node_cycle_fires_once() -> None:
    ont = make_ontology(
        links=[
            make_link("dependsOn", "a", "b"),
            make_link("dependsOn", "b", "c"),
            make_link("dependsOn", "c", "a"),
        ],
    )
    out = run_inference(ont, rule_filter="ontology.inference.acyclic_dependsOn")
    assert len(out) == 1


# ---------- irreflexive_dependsOn ---------------------------------------------


def test_irreflexive_dependsOn_self_loop_fires() -> None:
    ont = make_ontology(links=[make_link("dependsOn", "a", "a")])
    out = run_inference(
        ont, rule_filter="ontology.inference.irreflexive_dependsOn"
    )
    assert len(out) == 1
    assert out[0].subject_id is not None  # the offending link id
    assert "depends on itself" in out[0].detail


def test_irreflexive_dependsOn_normal_edge_silent() -> None:
    ont = make_ontology(links=[make_link("dependsOn", "a", "b")])
    out = run_inference(
        ont, rule_filter="ontology.inference.irreflexive_dependsOn"
    )
    assert out == []


# ---------- provider_must_be_documented ---------------------------------------


def test_provider_with_documented_claim_is_silent() -> None:
    ont = make_ontology(
        objects=[
            make_object(
                "lib-a",
                implements=[make_iface_claim("Documented")],
            ),
            make_object("proto-x", object_type="Protocol"),
        ],
        links=[
            make_link(
                "providesProtocol",
                "lib-a",
                "proto-x",
                to_type="Protocol",
            )
        ],
    )
    out = run_inference(
        ont,
        rule_filter="ontology.inference.provider_must_be_documented",
    )
    assert out == []


def test_provider_without_documented_claim_fires() -> None:
    ont = make_ontology(
        objects=[
            make_object("lib-a", implements=[]),
            make_object("proto-x", object_type="Protocol"),
        ],
        links=[
            make_link(
                "providesProtocol",
                "lib-a",
                "proto-x",
                to_type="Protocol",
            )
        ],
    )
    out = run_inference(
        ont,
        rule_filter="ontology.inference.provider_must_be_documented",
    )
    assert len(out) == 1
    assert out[0].subject_id == "lib-a"


# ---------- protocol_provider_must_be_releasable ------------------------------


def test_provider_with_releasable_claim_is_silent() -> None:
    ont = make_ontology(
        objects=[
            make_object(
                "lib-a",
                implements=[make_iface_claim("Releasable")],
            ),
            make_object("proto-x", object_type="Protocol"),
        ],
        links=[
            make_link(
                "providesProtocol",
                "lib-a",
                "proto-x",
                to_type="Protocol",
            )
        ],
    )
    out = run_inference(
        ont,
        rule_filter="ontology.inference.protocol_provider_must_be_releasable",
    )
    assert out == []


def test_provider_without_releasable_claim_fires() -> None:
    ont = make_ontology(
        objects=[
            make_object("lib-a", implements=[]),
            make_object("proto-x", object_type="Protocol"),
        ],
        links=[
            make_link(
                "providesProtocol",
                "lib-a",
                "proto-x",
                to_type="Protocol",
            )
        ],
    )
    out = run_inference(
        ont,
        rule_filter="ontology.inference.protocol_provider_must_be_releasable",
    )
    assert len(out) == 1


# ---------- consumer_must_pin_protocol_version --------------------------------


def test_consumer_with_at_version_pin_is_silent() -> None:
    ont = make_ontology(
        links=[
            make_link(
                "consumesProtocol",
                "consumer-a",
                "proto-x@1.0.0",
                to_type="Protocol",
            )
        ],
    )
    out = run_inference(
        ont,
        rule_filter="ontology.inference.consumer_must_pin_protocol_version",
    )
    assert out == []


def test_consumer_without_at_version_pin_fires() -> None:
    ont = make_ontology(
        links=[
            make_link(
                "consumesProtocol",
                "consumer-a",
                "proto-x",  # missing @X.Y.Z
                to_type="Protocol",
            )
        ],
    )
    out = run_inference(
        ont,
        rule_filter="ontology.inference.consumer_must_pin_protocol_version",
    )
    assert len(out) == 1
    assert "proto-x" in out[0].detail
    assert "consumer-a" in out[0].detail


# ---------- coupled_consumers_must_agree_on_major -----------------------------


def test_coupled_consumers_agreeing_silent() -> None:
    ont = make_ontology(
        links=[
            make_link(
                "consumesProtocol",
                "a",
                "proto@1.0.0",
                to_type="Protocol",
                link_id="a-consumes",
            ),
            make_link(
                "consumesProtocol",
                "b",
                "proto@1.0.0",
                to_type="Protocol",
                link_id="b-consumes",
            ),
            make_link("dependsOn", "a", "b"),
        ],
    )
    out = run_inference(
        ont,
        rule_filter="ontology.inference.coupled_consumers_must_agree_on_major",
    )
    assert out == []


def test_coupled_consumers_disagreeing_fires() -> None:
    """The value-prop demo case: a dependsOn b, both consume proto P,
    but a pins 0.10 and b pins 0.7 — should flag."""
    ont = make_ontology(
        links=[
            make_link(
                "consumesProtocol",
                "a",
                "proto@0.10.0",
                to_type="Protocol",
                link_id="a-consumes",
            ),
            make_link(
                "consumesProtocol",
                "b",
                "proto@0.7.0",
                to_type="Protocol",
                link_id="b-consumes",
            ),
            make_link("dependsOn", "a", "b"),
        ],
    )
    out = run_inference(
        ont,
        rule_filter="ontology.inference.coupled_consumers_must_agree_on_major",
    )
    assert len(out) == 1
    assert out[0].severity == "error"
    assert "proto" in out[0].detail
    assert "0.10" in out[0].detail
    assert "0.7" in out[0].detail


def test_coupled_consumers_disagree_dedup_per_pair() -> None:
    """If a and b each only consume the protocol once, the rule
    should emit exactly one violation per (protocol, pair), not one
    per direction or per link."""
    ont = make_ontology(
        links=[
            make_link(
                "consumesProtocol",
                "a",
                "proto@1.0.0",
                to_type="Protocol",
                link_id="a-1",
            ),
            make_link(
                "consumesProtocol",
                "b",
                "proto@2.0.0",
                to_type="Protocol",
                link_id="b-1",
            ),
            make_link("dependsOn", "a", "b"),
            make_link("dependsOn", "b", "a"),  # symmetric (will also trip acyclic)
        ],
    )
    out = run_inference(
        ont,
        rule_filter="ontology.inference.coupled_consumers_must_agree_on_major",
    )
    assert len(out) == 1
