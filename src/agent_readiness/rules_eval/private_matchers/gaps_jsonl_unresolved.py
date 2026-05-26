"""Private matcher: ``gaps_jsonl_unresolved``.

Reads ``.agent-readiness/gaps.jsonl`` from the repo root (per-workspace,
append-only JSONL written by the MCP server's gap-aware tools and by
the ``agent-readiness gap record`` CLI). Emits one finding per
unresolved :class:`Gap` row.

Clarification and Assumption rows are intentionally NOT surfaced as
findings — they're informational and visible via
``agent-readiness gap list``. Only Gaps cost score, and only until
they're flipped to ``resolved=true`` by ``agent-readiness gap resolve``.

The matcher silently produces no findings when the file is absent
(the common case for workspaces that haven't recorded any gaps yet);
malformed JSON lines are skipped without crashing the scan so a
hand-edited file with one bad line doesn't take the whole pillar
out of measurement.

Bundle B / B1 of the 2026-05-26 ontology-driven-agent design.
Added in agent-readiness v3.2.0; consumed by the
``ontology.gaps_unresolved`` rule shipped in
``agent-readiness-rules`` from v0.9.0+.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher

logger = logging.getLogger(__name__)


def match_gaps_jsonl_unresolved(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    """Return one finding per unresolved Gap row in ``.agent-readiness/gaps.jsonl``.

    ``cfg`` is accepted for parity with other private matchers but is
    currently unused (no tunables for this matcher — the gap file is
    always at ``.agent-readiness/gaps.jsonl`` relative to the repo
    root, and a Gap is unresolved iff ``resolved`` is not literally
    ``True``).
    """
    path = ctx.root / ".agent-readiness" / "gaps.jsonl"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover -- I/O failure mid-scan
        logger.debug("failed to read %s: %s", path, exc)
        return []

    findings: list[tuple[str | None, int | None, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            # Tolerate hand-edits; flag-by-skip rather than crash-the-scan.
            logger.debug(
                "skipping malformed JSONL row in %s (line %d)", path, lineno
            )
            continue
        if not isinstance(record, dict):
            continue
        if record.get("kind") != "gap":
            # Clarifications / Assumptions don't surface as findings.
            continue
        if record.get("resolved") is True:
            continue
        gap_id = record.get("id", "<no-id>")
        detail = record.get("detail", "<no detail>")
        msg = f"Unresolved gap {gap_id}: {detail}"
        findings.append((None, lineno, msg))
    return findings


register_private_matcher("gaps_jsonl_unresolved", match_gaps_jsonl_unresolved)
