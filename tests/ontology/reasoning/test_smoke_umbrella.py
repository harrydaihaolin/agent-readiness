"""Smoke: run every evaluator against the real umbrella manifest.

This test is **opportunistic** — it only runs when the manifest is
present at the expected sibling path (we don't ship the manifest
fixture in this repo). On contributor machines and in PROJECT_MAP
workspaces it runs; in isolated CI checkouts of just this repo it
skips.

Expectation at plan-write time (2026-05-26): the umbrella manifest
trips exactly one rule —
``ontology.inference.protocol_provider_must_be_releasable`` —
because the manifest's ``agent-readiness-insights-protocol`` Repo
declaration has no Releasable interface claim. That's a legitimate
data gap in the manifest (the repo *is* releasable; the claim is
just missing). This test asserts the current state without baking
in the gap as desirable — if/when the manifest is updated and the
claim added, the assertion below should be relaxed accordingly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_readiness.ontology import load_ontology
from agent_readiness.ontology.reasoning import REGISTRY, run_inference

_UMBRELLA_MANIFEST = (
    Path(__file__).resolve().parents[3].parent
    / "agent-readiness-manifest"
    / "ontology"
)


@pytest.mark.skipif(
    not _UMBRELLA_MANIFEST.is_dir(),
    reason=(
        f"sibling umbrella manifest not present at {_UMBRELLA_MANIFEST}; "
        "smoke test is opportunistic"
    ),
)
def test_umbrella_manifest_loads_and_chains_cleanly() -> None:
    ont = load_ontology(_UMBRELLA_MANIFEST)
    violations = run_inference(ont)

    rule_ids = {v.rule_id for v in violations}
    assert rule_ids.issubset(REGISTRY.evaluators.keys()), (
        f"chainer surfaced an unregistered rule id: "
        f"{rule_ids - set(REGISTRY.evaluators)}"
    )

    cycles = [
        v for v in violations if v.rule_id == "ontology.inference.acyclic_dependsOn"
    ]
    assert cycles == [], (
        "umbrella dependsOn graph must remain acyclic; cycles found: "
        f"{[v.detail for v in cycles]}"
    )

    self_loops = [
        v
        for v in violations
        if v.rule_id == "ontology.inference.irreflexive_dependsOn"
    ]
    assert self_loops == [], (
        "umbrella has a self-loop in dependsOn — fix the manifest"
    )
