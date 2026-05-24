from __future__ import annotations

from pathlib import Path

import pytest

from agent_readiness.ontology.runtime import (
    IntentNotFoundError,
    IntentStepError,
    advance_intent,
    list_active_intents,
    query_intent,
    record_intent,
)
from agent_readiness_insights_protocol.ontology.types import (
    IntentLedgerEntry,
    IntentStepStatus,
)


def test_record_intent_creates_ledger(intent_workspace: Path):
    result = record_intent(
        intent_workspace,
        "test_release",
        {"repo": "repo-a"},
        started_by="tester",
    )
    intent_id = result["intent_id"]
    ledger_path = intent_workspace / "ontology" / "intents" / f"{intent_id}.ledger.jsonl"
    assert ledger_path.is_file()
    lines = [line for line in ledger_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 3  # created + 2 steps
    for line in lines:
        IntentLedgerEntry.model_validate_json(line)
    assert result["steps"] == [
        {"step_id": "tag_repo", "status": "pending"},
        {"step_id": "blocked_step", "status": "pending"},
    ]


def test_record_intent_unknown_type(intent_workspace: Path):
    with pytest.raises(IntentNotFoundError):
        record_intent(intent_workspace, "missing_intent", {"repo": "repo-a"}, "tester")


def test_query_intent_pending_after_record(intent_workspace: Path):
    recorded = record_intent(
        intent_workspace,
        "test_release",
        {"repo": "repo-a"},
        started_by="tester",
    )
    state = query_intent(intent_workspace, recorded["intent_id"])
    assert state["overall_status"] == "in_progress"
    assert {step["status"] for step in state["steps"]} == {"pending"}


def test_advance_intent_dry_run_succeeds(intent_workspace: Path):
    recorded = record_intent(
        intent_workspace,
        "test_release",
        {"repo": "repo-a"},
        started_by="tester",
    )
    entry = advance_intent(
        intent_workspace,
        recorded["intent_id"],
        "tag_repo",
        dry_run=True,
    )
    assert entry["status"] == IntentStepStatus.COMMITTED.value
    state = query_intent(intent_workspace, recorded["intent_id"])
    tag_step = next(step for step in state["steps"] if step["step_id"] == "tag_repo")
    assert tag_step["status"] == "committed"


def test_advance_intent_blocked_by_preconditions(intent_workspace: Path):
    recorded = record_intent(
        intent_workspace,
        "test_release",
        {"repo": "repo-a"},
        started_by="tester",
    )
    entry = advance_intent(
        intent_workspace,
        recorded["intent_id"],
        "blocked_step",
        dry_run=True,
    )
    assert entry["status"] == IntentStepStatus.SKIPPED.value
    assert "missing-repo" in (entry.get("error_message") or "")


def test_advance_intent_idempotent_if_already_succeeded(intent_workspace: Path):
    recorded = record_intent(
        intent_workspace,
        "test_release",
        {"repo": "repo-a"},
        started_by="tester",
    )
    advance_intent(
        intent_workspace,
        recorded["intent_id"],
        "tag_repo",
        dry_run=True,
    )
    with pytest.raises(IntentStepError):
        advance_intent(
            intent_workspace,
            recorded["intent_id"],
            "tag_repo",
            dry_run=True,
        )


def test_list_active_intents_filters_completed(intent_workspace: Path):
    active = record_intent(
        intent_workspace,
        "test_release",
        {"repo": "repo-a"},
        started_by="tester",
    )
    done = record_intent(
        intent_workspace,
        "test_release",
        {"repo": "repo-b"},
        started_by="tester",
    )
    advance_intent(intent_workspace, done["intent_id"], "tag_repo", dry_run=True)
    advance_intent(intent_workspace, done["intent_id"], "blocked_step", dry_run=True)

    active_intents = list_active_intents(intent_workspace)
    active_ids = {item["intent_id"] for item in active_intents}
    assert active["intent_id"] in active_ids
    assert done["intent_id"] not in active_ids
