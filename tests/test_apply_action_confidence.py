"""``apply_top_action`` branches on per-rule confidence (Bundle B / B2).

The contract:

* ``confidence == "high"``   → applies the structured action as
  before (the v3.1 behaviour).
* ``confidence == "medium"`` → refuses to mutate; returns an
  envelope with ``confirm_required=True`` so the MCP layer's
  ``confirm_apply`` tool can finish the round-trip with a human.
* ``confidence == "low"``    → refuses to mutate; returns
  ``gap_payload`` so the MCP layer can ``record_gap()`` and surface
  the unresolved ambiguity on the next scan.

Missing ``confidence`` key defaults to ``"medium"`` to match the
protocol's :class:`Rule.confidence` default — never silently fall
through to apply.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_readiness.apply_action import apply_top_action


def _stub_top_action(*, confidence: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "check_id": "test.stub",
        "pillar": "flow",
        "severity": "warn",
        "message": "stub finding for confidence branching test",
        "weight": 1.0,
        "rationale": "stub",
        "fix_hint": "create stub.txt with hi",
        "action": {
            "kind": "create_file",
            "path": "stub.txt",
            "template": "hi\n",
        },
        "verify": {"command": "test -f stub.txt", "description": ""},
    }
    if confidence is not None:
        payload["confidence"] = confidence
    return payload


def test_high_confidence_applies_and_writes(tmp_path: Path) -> None:
    result = apply_top_action(_stub_top_action(confidence="high"), tmp_path)
    assert result.applied is True, result.error
    assert result.skipped_reason is None
    assert result.confirm_required is False
    assert result.gap_payload is None
    assert (tmp_path / "stub.txt").exists()
    assert (tmp_path / "stub.txt").read_text() == "hi\n"


def test_medium_confidence_returns_confirm_required(tmp_path: Path) -> None:
    result = apply_top_action(_stub_top_action(confidence="medium"), tmp_path)
    assert result.applied is False
    assert result.skipped_reason == "confirm_required"
    assert result.confirm_required is True
    assert result.gap_payload is None
    assert not (tmp_path / "stub.txt").exists()


def test_low_confidence_returns_gap_payload(tmp_path: Path) -> None:
    result = apply_top_action(_stub_top_action(confidence="low"), tmp_path)
    assert result.applied is False
    assert result.skipped_reason == "low_confidence_record_gap"
    assert result.gap_payload is not None
    assert result.gap_payload["kind"] == "low_confidence_top_action"
    assert result.gap_payload["check_id"] == "test.stub"
    assert "candidate_resolutions" in result.gap_payload
    assert result.gap_payload["candidate_resolutions"] == [
        "create stub.txt with hi"
    ]
    assert not (tmp_path / "stub.txt").exists()


def test_missing_confidence_defaults_to_medium_branch(tmp_path: Path) -> None:
    """Defensive: no ``confidence`` key must not silently mutate."""
    result = apply_top_action(_stub_top_action(confidence=None), tmp_path)
    assert result.applied is False
    assert result.skipped_reason == "confirm_required"
    assert result.confirm_required is True
    assert not (tmp_path / "stub.txt").exists()


def test_to_dict_omits_confirm_required_when_false() -> None:
    """ApplyResult.to_dict strips default-False ``confirm_required``."""
    from agent_readiness.apply_action import ApplyResult

    res = ApplyResult(applied=True, written=["x"])
    d = res.to_dict()
    assert "confirm_required" not in d
    assert "gap_payload" not in d


def test_to_dict_carries_gap_payload_when_set() -> None:
    from agent_readiness.apply_action import ApplyResult

    res = ApplyResult(
        applied=False,
        skipped_reason="low_confidence_record_gap",
        gap_payload={"kind": "low_confidence_top_action", "detail": "x"},
    )
    d = res.to_dict()
    assert d["gap_payload"]["kind"] == "low_confidence_top_action"
    assert d["skipped_reason"] == "low_confidence_record_gap"


@pytest.mark.parametrize("conf", ["high", "medium", "low"])
def test_branch_runs_even_with_unknown_action_kind(
    tmp_path: Path, conf: str
) -> None:
    """Confidence gating fires BEFORE handler resolution.

    A medium/low rule with a typo'd ``action.kind`` should still be
    refused with the confidence envelope, not a "unknown action kind"
    error. High-confidence with a bad kind still errors out — that's
    the existing contract.
    """
    payload = _stub_top_action(confidence=conf)
    payload["action"] = {"kind": "wipe_disk", "path": "x"}

    result = apply_top_action(payload, tmp_path)

    if conf == "high":
        assert result.applied is False
        assert result.error is not None
        assert "unknown action kind" in result.error
    elif conf == "medium":
        assert result.confirm_required is True
    else:
        assert result.gap_payload is not None
