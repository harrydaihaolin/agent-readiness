"""Private matcher: ``ontology_inference``.

Bridges YAML rules in ``agent-readiness-rules`` under
``rules/ontology/inference/`` to the forward chainer in
:mod:`agent_readiness.ontology.reasoning`. Each ``inference`` rule
references this matcher and passes its own ``rule_id`` in the
config so the matcher knows which evaluator to delegate to.

Why a single matcher (rather than one matcher per inference rule):
the chainer's REGISTRY is the source of truth for which rules
exist. Adding a new evaluator should only require dropping a module
into ``agent_readiness.ontology.reasoning.evaluators``; the YAML
rule referring to it pipes through this matcher unchanged. The
matcher's only responsibility is locating the ontology root,
loading the graph, running the named evaluator, and reshaping the
violations as ``(file, line, msg)`` tuples for the rules engine.

Ontology root resolution (in priority order):

1. ``cfg["ontology_root"]`` — explicit override (used by tests).
2. ``<ctx.root>/ontology`` — single-repo workspace layout.
3. ``<ctx.root>/agent-readiness-manifest/ontology`` — umbrella layout
   where the manifest is a sibling directory.

If none resolve, the matcher returns ``[]`` (no findings) — same
"silent on missing input" contract as ``gaps_jsonl_unresolved``.

Bundle C of the 2026-05-26 ontology-driven-agent design. Added in
agent-readiness v3.3.0; consumed by the
``ontology.inference.*`` rules shipped in ``agent-readiness-rules``
from PROTOCOL_TAG v0.10.0+.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher

logger = logging.getLogger(__name__)


def _resolve_ontology_root(ctx: RepoContext, cfg: dict[str, Any]) -> Path | None:
    override = cfg.get("ontology_root")
    if override:
        p = Path(override)
        if not p.is_absolute():
            p = ctx.root / p
        return p if p.is_dir() else None

    in_repo = ctx.root / "ontology"
    if in_repo.is_dir():
        return in_repo

    umbrella = ctx.root / "agent-readiness-manifest" / "ontology"
    if umbrella.is_dir():
        return umbrella

    return None


def match_ontology_inference(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    """Run one inference evaluator and reshape its violations as findings.

    ``cfg`` must include ``rule_id`` — the full
    ``ontology.inference.<name>`` id of the rule that referenced this
    matcher. If the id is unregistered (e.g. an evaluator wasn't
    imported), the matcher returns ``[]`` and logs a debug message
    rather than crashing the scan.
    """
    rule_id = cfg.get("rule_id")
    if not isinstance(rule_id, str) or not rule_id:
        logger.debug("ontology_inference matcher invoked without cfg['rule_id']")
        return []

    ontology_root = _resolve_ontology_root(ctx, cfg)
    if ontology_root is None:
        return []

    try:
        from agent_readiness.ontology.loader import load_ontology
        from agent_readiness.ontology.reasoning import run_inference
    except ImportError as exc:  # pragma: no cover -- defensive
        logger.debug("reasoning module unavailable: %s", exc)
        return []

    try:
        ont = load_ontology(ontology_root)
    except Exception as exc:  # noqa: BLE001 -- defensive across YAML/pydantic/IO
        # load_ontology itself raises ValueError on pydantic errors, but
        # PyYAML raises its own ScannerError subclass on malformed YAML
        # and OS errors can bubble through on permission/encoding issues.
        # The scan must not crash on a single bad ontology atom.
        logger.debug("ontology at %s did not load: %s", ontology_root, exc)
        return []

    violations = run_inference(ont, rule_filter=rule_id)
    return [(None, None, v.detail) for v in violations]


register_private_matcher("ontology_inference", match_ontology_inference)
