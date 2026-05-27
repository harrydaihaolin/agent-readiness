"""Tests for live_scan.prompts (Bundle D).

Covers the request/answer/expire state machine, default-action
fallback on timeout, supersede semantics for late answers, and
prompts.jsonl persistence/recovery.
"""
from __future__ import annotations

import json

import pytest

from agent_readiness.live_scan.events import EventLog
from agent_readiness.live_scan.prompts import PromptLog, prompts_path
from agent_readiness_insights_protocol import (
    ClarifyAnswer,
    ClarifyPromptPayload,
    ClassifyAnswer,
    ClassifyOption,
    ClassifyPromptPayload,
    MembersAnswer,
    MembersCandidate,
    MembersPromptPayload,
)


def _fresh(tmp_path):
    el = EventLog(tmp_path)
    return PromptLog(tmp_path, el), el


def test_enqueue_writes_record_and_emits_sse(tmp_path):
    pl, el = _fresh(tmp_path)
    pid = pl.enqueue(
        payload=ClassifyPromptPayload(
            options=[ClassifyOption(id="m", label="monorepo", confidence=0.9)],
        ),
        default_action=ClassifyAnswer(option_id="m"),
        blocking=True,
        timeout_s=30,
    )
    assert pid.startswith("p-")
    assert pl.status(pid) == "pending"
    assert pl.pending_count() == 1

    # Persisted to prompts.jsonl
    on_disk = prompts_path(tmp_path).read_text().strip().splitlines()
    assert len(on_disk) == 1
    record = json.loads(on_disk[0])
    assert record["event"] == "requested"
    assert record["prompt_id"] == pid
    assert record["blocking"] is True

    # Mirrored as SSE event
    assert el.next_seq == 1


def test_answer_marks_answered_and_emits_sse(tmp_path):
    pl, el = _fresh(tmp_path)
    pid = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="default"),
    )
    pl.answer(pid, answer=ClarifyAnswer(freeform="user response"), source="browser")
    assert pl.status(pid) == "answered"
    assert pl.is_answered(pid)
    assert el.next_seq == 2  # requested + answered


def test_answer_unknown_prompt_raises(tmp_path):
    pl, _ = _fresh(tmp_path)
    with pytest.raises(KeyError):
        pl.answer("p-nope", answer=ClarifyAnswer(freeform="x"), source="browser")


def test_answer_invalid_source_raises(tmp_path):
    pl, _ = _fresh(tmp_path)
    pid = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="d"),
    )
    with pytest.raises(ValueError):
        pl.answer(pid, answer=ClarifyAnswer(freeform="x"), source="bogus")


def test_expire_applies_default_action(tmp_path):
    pl, el = _fresh(tmp_path)
    pid = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="DEFAULT_VAL"),
    )
    pl.expire(pid)
    assert pl.status(pid) == "default_applied"
    assert el.next_seq == 2  # requested + expired


def test_expire_is_idempotent(tmp_path):
    pl, el = _fresh(tmp_path)
    pid = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="x"),
    )
    pl.expire(pid)
    pl.expire(pid)
    pl.expire(pid)
    assert el.next_seq == 2  # requested + ONE expired
    assert pl.status(pid) == "default_applied"


def test_supersede_after_default_applied(tmp_path):
    """User answers AFTER default was applied → state becomes 'superseded'.

    Per spec § 9.1: the default's already been written to the
    workspace; the answer takes effect for FUTURE evaluators only.
    """
    pl, _ = _fresh(tmp_path)
    pid = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="d"),
    )
    pl.expire(pid)
    pl.answer(pid, answer=ClarifyAnswer(freeform="late"), source="browser")
    assert pl.status(pid) == "superseded"
    assert pl.is_answered(pid)


def test_wait_for_answer_returns_when_answered(tmp_path):
    """wait_for_answer should return immediately when the answer is
    already present (pre-scan flow with skill writing answers up front)."""
    pl, _ = _fresh(tmp_path)
    pid = pl.enqueue(
        payload=MembersPromptPayload(
            candidates=[MembersCandidate(id="r1", name="r1", path="/x",
                                          detected_type="single_repo")],
            preselected=["r1"],
        ),
        default_action=MembersAnswer(included=["r1"]),
    )
    pl.answer(pid, answer=MembersAnswer(included=["r1", "r2"]), source="browser")
    result = pl.wait_for_answer(pid, timeout_s=5.0)
    assert result == {"type": "members", "included": ["r1", "r2"]}


def test_wait_for_answer_applies_default_on_timeout(tmp_path):
    pl, _ = _fresh(tmp_path)
    pid = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="DEFAULT_VAL"),
    )
    result = pl.wait_for_answer(pid, timeout_s=0.05)
    assert pl.status(pid) == "default_applied"
    assert result["freeform"] == "DEFAULT_VAL"


def test_default_used_for_lists_expired_and_superseded(tmp_path):
    pl, _ = _fresh(tmp_path)
    p1 = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="d1"),
    )
    p2 = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="d2"),
    )
    # p3 left pending — deliberately unassigned, just exercising the
    # "still pending after some defaults" path.
    pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="d3"),
    )
    pl.expire(p1)
    pl.expire(p2)
    pl.answer(p2, answer=ClarifyAnswer(freeform="late"), source="browser")
    # p3 left pending
    assert set(pl.default_used_for()) == {p1, p2}


def test_reindex_rehydrates_state_from_disk(tmp_path):
    pl, _ = _fresh(tmp_path)
    p1 = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="d"),
    )
    p2 = pl.enqueue(
        payload=ClarifyPromptPayload(question="?"),
        default_action=ClarifyAnswer(freeform="d"),
    )
    pl.answer(p1, answer=ClarifyAnswer(freeform="x"), source="browser")
    pl.expire(p2)

    pl2 = PromptLog(tmp_path, EventLog(tmp_path))
    assert pl2.status(p1) == "answered"
    assert pl2.status(p2) == "default_applied"
    assert pl2.is_known(p1)
    assert pl2.is_known(p2)


def test_list_pending_returns_only_pending_with_payload(tmp_path):
    pl, _ = _fresh(tmp_path)
    p1 = pl.enqueue(
        payload=ClarifyPromptPayload(question="open"),
        default_action=ClarifyAnswer(freeform="d"),
        blocking=False,
    )
    p2 = pl.enqueue(
        payload=ClarifyPromptPayload(question="closed"),
        default_action=ClarifyAnswer(freeform="d"),
    )
    pl.answer(p2, answer=ClarifyAnswer(freeform="x"), source="browser")
    pending = pl.list_pending()
    assert len(pending) == 1
    assert pending[0]["prompt_id"] == p1
    assert pending[0]["payload"]["question"] == "open"
