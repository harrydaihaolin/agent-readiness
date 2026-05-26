"""Tests for the ``gaps_jsonl_unresolved`` private matcher (Bundle B / B1).

Surfaces one finding per *unresolved* :class:`Gap` row in
``.agent-readiness/gaps.jsonl``. Clarification and Assumption rows
never produce findings (informational only); resolved Gap rows never
produce findings (they're audit history at that point). The matcher
is also tolerant of malformed JSONL rows: a hand-edited file with one
bad line must not crash the rest of the scan.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval.private_matchers.gaps_jsonl_unresolved import (
    match_gaps_jsonl_unresolved,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_no_file_means_no_findings(tmp_path: Path) -> None:
    """Common case: a workspace that has never recorded any gaps."""
    ctx = RepoContext(root=tmp_path)
    assert match_gaps_jsonl_unresolved(ctx, {}) == []


def test_single_unresolved_gap_produces_one_finding(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / ".agent-readiness" / "gaps.jsonl",
        [
            {
                "kind": "gap",
                "id": "gap-001",
                "detail": "ambiguous Object Type — Repo or Library?",
                "resolved": False,
            }
        ],
    )
    ctx = RepoContext(root=tmp_path)
    findings = match_gaps_jsonl_unresolved(ctx, {})
    assert len(findings) == 1
    msg = findings[0][2]
    assert "gap-001" in msg
    assert "ambiguous Object Type" in msg


def test_resolved_gap_is_skipped(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / ".agent-readiness" / "gaps.jsonl",
        [
            {
                "kind": "gap",
                "id": "gap-002",
                "detail": "fixed already",
                "resolved": True,
            }
        ],
    )
    ctx = RepoContext(root=tmp_path)
    assert match_gaps_jsonl_unresolved(ctx, {}) == []


def test_clarification_and_assumption_rows_never_fire(tmp_path: Path) -> None:
    """Only Gap rows cost score; Clarification/Assumption are info-only."""
    _write_jsonl(
        tmp_path / ".agent-readiness" / "gaps.jsonl",
        [
            {
                "kind": "clarification",
                "id": "clar-001",
                "question": "which interface?",
                "resolved": False,
            },
            {
                "kind": "assumption",
                "id": "assume-001",
                "assumption": "Python library, not CLI",
                "justification": "no [project.scripts]",
            },
        ],
    )
    ctx = RepoContext(root=tmp_path)
    assert match_gaps_jsonl_unresolved(ctx, {}) == []


def test_mixed_file_surfaces_only_unresolved_gaps(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / ".agent-readiness" / "gaps.jsonl",
        [
            {"kind": "gap", "id": "gap-a", "detail": "open", "resolved": False},
            {"kind": "gap", "id": "gap-b", "detail": "done", "resolved": True},
            {"kind": "assumption", "id": "as-1", "assumption": "x", "justification": "y"},
            {"kind": "gap", "id": "gap-c", "detail": "still open", "resolved": False},
        ],
    )
    ctx = RepoContext(root=tmp_path)
    findings = match_gaps_jsonl_unresolved(ctx, {})
    assert len(findings) == 2
    ids = {f[2].split()[2].rstrip(":") for f in findings}
    assert ids == {"gap-a", "gap-c"}


def test_tolerates_malformed_json_line(tmp_path: Path) -> None:
    """A hand-edited file with one bad line must not break the scan."""
    path = tmp_path / ".agent-readiness" / "gaps.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"kind": "gap", "id": "gap-x", "detail": "ok", "resolved": False})
        + "\nthis is not valid JSON\n"
        + json.dumps({"kind": "gap", "id": "gap-y", "detail": "also ok", "resolved": False})
        + "\n"
    )
    ctx = RepoContext(root=tmp_path)
    findings = match_gaps_jsonl_unresolved(ctx, {})
    assert len(findings) == 2


def test_missing_resolved_field_counts_as_unresolved(tmp_path: Path) -> None:
    """Defensive: an older record without `resolved` should still fire."""
    path = tmp_path / ".agent-readiness" / "gaps.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"kind": "gap", "id": "gap-old", "detail": "no resolved key"})
        + "\n"
    )
    ctx = RepoContext(root=tmp_path)
    findings = match_gaps_jsonl_unresolved(ctx, {})
    assert len(findings) == 1
    assert "gap-old" in findings[0][2]
