"""Workspace-local Gap / Clarification / Assumption storage.

Writes to ``.agent-readiness/gaps.jsonl`` in the *current working
directory* (the workspace root), append-only, with ``fcntl.flock`` for
concurrent-writer safety across parallel agent sessions. Records are
one JSON object per line; the top-level ``"kind"`` field
discriminates between :class:`Gap`, :class:`Clarification`, and
:class:`Assumption` rows so a single file can carry all three without
schema collisions.

Field-name note: :class:`Gap` and the JSONL row both have a ``kind``
field, but they mean different things. The JSONL row's ``"kind"`` is
the discriminator (``"gap"`` / ``"clarification"`` / ``"assumption"``);
the Gap model's ``kind`` is the agent-supplied classification of *what*
was ambiguous (``"ambiguous_object_type"``, etc.). We resolve the
collision in this module by storing the agent-supplied value under
``"gap_kind"`` on disk; consumers that load Gap rows back into the
protocol model are responsible for mapping ``gap_kind → kind``.

This module deliberately keeps no in-memory state — every call hits
the file. Workloads are tiny (O(100) gaps per workspace at the high
end) so the constant overhead is fine and frees us from cache-
invalidation bugs across processes.

Bundle B / B1 of the 2026-05-26 ontology-driven-agent design.
Added in agent-readiness v3.2.0.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "GAPS_FILE",
    "list_gaps",
    "record_assumption",
    "record_clarification",
    "record_gap",
    "resolve_gap",
]

GAPS_FILE = Path(".agent-readiness") / "gaps.jsonl"
"""Path to the gaps JSONL, relative to the workspace root (cwd).

Exposed so MCP / dogfood callers can document the on-disk location
without hard-coding the literal in two places.
"""


def _gaps_path(*, root: Path | None = None) -> Path:
    """Resolve the gaps file relative to ``root`` (default: cwd).

    The ``root`` override is exposed primarily for tests that don't
    want to ``cd`` into ``tmp_path`` — production callers always
    invoke from the workspace root.
    """
    base = root if root is not None else Path.cwd()
    return base / GAPS_FILE


def _new_id(prefix: str) -> str:
    """Stable-ish locally-unique id.

    ``<prefix>-<unix-ts>-<8-hex>`` is sortable (timestamp is leading)
    and has enough entropy that two parallel agent sessions calling
    ``record_gap`` at the same second still collide-free with
    overwhelming probability.
    """
    return f"{prefix}-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def _now_iso_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _append(record: dict[str, Any], *, root: Path | None = None) -> None:
    """Append ``record`` as a JSON line, under an exclusive file lock."""
    path = _gaps_path(root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def record_gap(
    *,
    kind: str,
    detail: str,
    severity: str = "medium",
    candidate_resolutions: list[str] | None = None,
    agent_session: str | None = None,
    root: Path | None = None,
) -> str:
    """Append a new Gap row and return its id.

    ``kind`` is the agent's classification of *what* was ambiguous
    (``"ambiguous_object_type"``, ``"low_confidence_top_action"``, …),
    stored under ``"gap_kind"`` on disk to avoid colliding with the
    JSONL ``"kind"`` discriminator. ``candidate_resolutions`` is an
    optional shortlist of candidate fixes the agent considered.
    """
    new_id = _new_id("gap")
    record = {
        "kind": "gap",
        "id": new_id,
        "gap_kind": kind,
        "detail": detail,
        "candidate_resolutions": list(candidate_resolutions or []),
        "severity": severity,
        "resolved": False,
        "agent_session": agent_session,
        "timestamp": _now_iso_utc(),
    }
    _append(record, root=root)
    return new_id


def record_clarification(
    *,
    question: str,
    options: list[str] | None = None,
    context_path: str | None = None,
    agent_session: str | None = None,
    root: Path | None = None,
) -> str:
    """Append a new Clarification row and return its id."""
    new_id = _new_id("clar")
    record = {
        "kind": "clarification",
        "id": new_id,
        "question": question,
        "options": list(options or []),
        "context_path": context_path,
        "resolved": False,
        "agent_session": agent_session,
        "timestamp": _now_iso_utc(),
    }
    _append(record, root=root)
    return new_id


def record_assumption(
    *,
    assumption: str,
    justification: str,
    expires_after: str | None = None,
    agent_session: str | None = None,
    root: Path | None = None,
) -> str:
    """Append a new Assumption row and return its id."""
    new_id = _new_id("assume")
    record = {
        "kind": "assumption",
        "id": new_id,
        "assumption": assumption,
        "justification": justification,
        "expires_after": expires_after,
        "agent_session": agent_session,
        "timestamp": _now_iso_utc(),
    }
    _append(record, root=root)
    return new_id


def list_gaps(
    *, include_resolved: bool = False, root: Path | None = None
) -> list[dict[str, Any]]:
    """Return Gap rows (Clarifications/Assumptions are excluded).

    By default only unresolved gaps are returned — those are the ones
    that cost score via ``ontology.gaps_unresolved``. Set
    ``include_resolved=True`` to audit the full history.
    """
    path = _gaps_path(root=root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("kind") != "gap":
            continue
        if rec.get("resolved") and not include_resolved:
            continue
        out.append(rec)
    return out


def resolve_gap(gap_id: str, *, root: Path | None = None) -> bool:
    """Mark the gap with ``gap_id`` as resolved.

    Returns ``True`` if the gap was found (and resolved), ``False``
    otherwise. The whole file is rewritten under an exclusive lock —
    keeps the append-only invariant easy to reason about by re-
    emitting every row, with only the matching gap's ``resolved``
    flag flipped. Cheap for the file sizes we expect (O(100) lines).
    """
    path = _gaps_path(root=root)
    if not path.is_file():
        return False
    with path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            lines = fh.read().splitlines()
            new_lines: list[str] = []
            found = False
            for line in lines:
                if not line.strip():
                    new_lines.append(line)
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    new_lines.append(line)
                    continue
                if (
                    isinstance(rec, dict)
                    and rec.get("kind") == "gap"
                    and rec.get("id") == gap_id
                ):
                    rec["resolved"] = True
                    found = True
                new_lines.append(json.dumps(rec, sort_keys=True))
            if found:
                fh.seek(0)
                fh.truncate()
                fh.write("\n".join(new_lines) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return found
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
