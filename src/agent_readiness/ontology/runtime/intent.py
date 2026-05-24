"""M4.3 — intent ledger runtime tools."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_readiness.ontology.runtime.action import (
    ActionExecutionError,
    apply_action,
)
from agent_readiness.ontology.runtime.data import get_object, query_objects
from agent_readiness_insights_protocol.ontology.types import (
    IntentLedgerEntry,
    IntentStepStatus,
    IntentType,
)

CREATED_STEP_ID = "__created__"


class IntentNotFoundError(LookupError):
    """Raised when an intent ledger or IntentType is missing."""


class IntentStepError(RuntimeError):
    """Raised when advancing an intent step is invalid or blocked."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utcnow_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _slug(goal_args: dict[str, Any]) -> str:
    parts = [str(goal_args[k]) for k in sorted(goal_args)]
    slug = "-".join(re.sub(r"[^a-z0-9-]+", "-", part.lower()).strip("-") for part in parts)
    return slug[:80] or "goal"


def _intents_dir(workspace: Path) -> Path:
    return workspace / "ontology" / "intents"


def _ledger_path(workspace: Path, intent_id: str) -> Path:
    return _intents_dir(workspace) / f"{intent_id}.ledger.jsonl"


def _meta_path(workspace: Path, intent_id: str) -> Path:
    return _intents_dir(workspace) / f"{intent_id}.meta.json"


def _load_intent_type(workspace: Path, intent_type: str) -> IntentType:
    path = workspace / "ontology" / "intentTypes" / f"{intent_type}.yaml"
    if not path.is_file():
        raise IntentNotFoundError(
            f"IntentType not found: {intent_type} (expected {path})"
        )
    data = yaml.safe_load(path.read_text())
    return IntentType.model_validate(data)


def _append_ledger_entry(path: Path, entry: IntentLedgerEntry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")


def _read_ledger(path: Path) -> list[IntentLedgerEntry]:
    if not path.is_file():
        raise IntentNotFoundError(f"Intent ledger not found: {path}")
    entries: list[IntentLedgerEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(IntentLedgerEntry.model_validate_json(line))
    return entries


def _load_meta(workspace: Path, intent_id: str) -> dict[str, Any]:
    path = _meta_path(workspace, intent_id)
    if not path.is_file():
        raise IntentNotFoundError(f"Intent metadata not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _step_definitions(meta: dict[str, Any]) -> list[dict[str, Any]]:
    return list(meta.get("steps") or [])


def _latest_status_by_step(entries: list[IntentLedgerEntry]) -> dict[str, IntentStepStatus]:
    status_by_step: dict[str, IntentStepStatus] = {}
    for entry in entries:
        status_by_step[entry.step_id] = entry.status
    return status_by_step


def _overall_status(
    step_defs: list[dict[str, Any]], status_by_step: dict[str, IntentStepStatus]
) -> str:
    actionable = [step["id"] for step in step_defs if step.get("id")]
    if not actionable:
        return "succeeded"
    if any(status_by_step.get(step_id) == IntentStepStatus.FAILED for step_id in actionable):
        return "failed"
    if any(
        status_by_step.get(step_id) in (IntentStepStatus.PENDING, IntentStepStatus.IN_FLIGHT)
        for step_id in actionable
    ):
        return "in_progress"
    return "succeeded"


def _evaluate_preconditions(
    workspace: Path, preconditions: list[dict[str, Any]]
) -> tuple[bool, str | None]:
    for precondition in preconditions:
        if "object_id" in precondition:
            obj_id = str(precondition["object_id"])
            if get_object(workspace, obj_id) is None:
                return False, f"object not found: {obj_id}"
            continue
        if "object_type" in precondition:
            object_type = str(precondition["object_type"])
            where = precondition.get("where") or {}
            expect = int(precondition.get("expect", 1))
            found = query_objects(workspace, object_type, where=where or None)
            if len(found) != expect:
                return False, (
                    f"query_objects({object_type}, {where}) returned "
                    f"{len(found)} rows, expected {expect}"
                )
            continue
        return False, f"unsupported precondition: {precondition}"
    return True, None


def _resolve_step_args(step: dict[str, Any], goal_args: dict[str, Any]) -> dict[str, Any]:
    raw_args = step.get("args") or {}
    resolved: dict[str, Any] = {}
    for key, value in raw_args.items():
        if isinstance(value, str) and value in goal_args:
            resolved[key] = goal_args[value]
        else:
            resolved[key] = value
    return resolved


def record_intent(
    workspace: Path,
    intent_type: str,
    goal_args: dict[str, Any],
    started_by: str,
) -> dict[str, Any]:
    """Create an intent ledger with one PENDING entry per declared step."""
    intent_def = _load_intent_type(workspace, intent_type)
    spec = intent_def.spec or {}
    step_defs = list(spec.get("steps") or [])
    intent_id = f"{intent_type}--{_slug(goal_args)}--{_utcnow_ms()}"
    now = _utcnow_iso()

    ledger = _ledger_path(workspace, intent_id)
    created = IntentLedgerEntry(
        intent_id=intent_id,
        step_id=CREATED_STEP_ID,
        status=IntentStepStatus.COMMITTED,
        started_at=now,
        ended_at=now,
    )
    _append_ledger_entry(ledger, created)

    for step in step_defs:
        step_id = str(step["id"])
        entry = IntentLedgerEntry(
            intent_id=intent_id,
            step_id=step_id,
            status=IntentStepStatus.PENDING,
            started_at=now,
        )
        _append_ledger_entry(ledger, entry)

    meta = {
        "intent_id": intent_id,
        "intent_type": intent_type,
        "goal_args": goal_args,
        "started_by": started_by,
        "steps": step_defs,
    }
    _meta_path(workspace, intent_id).write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    return {
        "intent_id": intent_id,
        "intent_type": intent_type,
        "steps": [{"step_id": step["id"], "status": "pending"} for step in step_defs],
        "status": "pending",
    }


def query_intent(workspace: Path, intent_id: str) -> dict[str, Any]:
    """Return consolidated intent state from the ledger."""
    ledger = _ledger_path(workspace, intent_id)
    entries = _read_ledger(ledger)
    meta = _load_meta(workspace, intent_id)
    step_defs = _step_definitions(meta)
    status_by_step = _latest_status_by_step(entries)

    steps_out: list[dict[str, Any]] = []
    for step in step_defs:
        step_id = str(step["id"])
        status = status_by_step.get(step_id, IntentStepStatus.PENDING)
        attempted = [
            entry
            for entry in entries
            if entry.step_id == step_id and entry.step_id != CREATED_STEP_ID
        ]
        last = attempted[-1] if attempted else None
        steps_out.append(
            {
                "step_id": step_id,
                "status": status.value,
                "attempted_at": last.started_at if last else None,
                "action_id": step.get("action"),
                "args": step.get("args"),
            }
        )

    return {
        "intent_id": intent_id,
        "intent_type": meta["intent_type"],
        "steps": steps_out,
        "overall_status": _overall_status(step_defs, status_by_step),
    }


def advance_intent(
    workspace: Path,
    intent_id: str,
    step_id: str,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Advance a single intent step, optionally executing its underlying action."""
    ledger_path = _ledger_path(workspace, intent_id)
    entries = _read_ledger(ledger_path)
    meta = _load_meta(workspace, intent_id)
    step_defs = _step_definitions(meta)
    step_def = next((step for step in step_defs if step["id"] == step_id), None)
    if step_def is None:
        raise IntentStepError(f"Unknown step_id {step_id!r} for intent {intent_id!r}")

    status_by_step = _latest_status_by_step(entries)
    current = status_by_step.get(step_id)
    if current in (IntentStepStatus.COMMITTED, IntentStepStatus.FAILED):
        raise IntentStepError(
            f"Step {step_id!r} already terminal ({current.value}); refusing re-advance"
        )

    preconditions = list(step_def.get("preconditions") or [])
    ok, reason = _evaluate_preconditions(workspace, preconditions)
    now = _utcnow_iso()
    if not ok:
        blocked = IntentLedgerEntry(
            intent_id=intent_id,
            step_id=step_id,
            status=IntentStepStatus.SKIPPED,
            started_at=now,
            ended_at=now,
            error_message=reason,
        )
        _append_ledger_entry(ledger_path, blocked)
        return blocked.model_dump(mode="json")

    action_id = str(step_def.get("action") or "")
    if not action_id:
        raise IntentStepError(f"Step {step_id!r} has no action declared")

    resolved_args = _resolve_step_args(step_def, meta.get("goal_args") or {})
    try:
        apply_action(workspace, action_id, resolved_args, dry_run=dry_run)
        status = IntentStepStatus.COMMITTED
        error_message = None
    except ActionExecutionError as exc:
        status = IntentStepStatus.FAILED
        error_message = str(exc)

    entry = IntentLedgerEntry(
        intent_id=intent_id,
        step_id=step_id,
        status=status,
        started_at=now,
        ended_at=now,
        error_message=error_message,
    )
    _append_ledger_entry(ledger_path, entry)
    return entry.model_dump(mode="json")


def list_active_intents(workspace: Path) -> list[dict[str, Any]]:
    """Return intents whose overall_status is ``in_progress``."""
    intents_dir = _intents_dir(workspace)
    if not intents_dir.is_dir():
        return []

    active: list[dict[str, Any]] = []
    for meta_path in sorted(intents_dir.glob("*.meta.json")):
        intent_id = meta_path.stem.replace(".meta", "")
        state = query_intent(workspace, intent_id)
        if state["overall_status"] != "in_progress":
            continue
        meta = _load_meta(workspace, intent_id)
        pending = [
            step["step_id"]
            for step in state["steps"]
            if step["status"] in ("pending", "in_flight")
        ]
        entries = _read_ledger(_ledger_path(workspace, intent_id))
        created = next((entry for entry in entries if entry.step_id == CREATED_STEP_ID), None)
        active.append(
            {
                "intent_id": intent_id,
                "intent_type": meta["intent_type"],
                "pending_step_ids": pending,
                "started_at": created.started_at if created else None,
                "started_by": meta.get("started_by"),
            }
        )
    return active
