"""M4.3 — apply_action runtime tool."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_readiness.ontology.runtime.drivers import (
    DriverAuthError,
    DriverNotFoundError,
    DriverUnavailableError,
    get_driver,
)
from agent_readiness_insights_protocol.ontology.types import ActionType


class ActionNotFoundError(LookupError):
    """Raised when the requested ActionType YAML is missing."""


class ActionExecutionError(RuntimeError):
    """Raised when action execution fails."""

    def __init__(self, action_id: str, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(f"{action_id}: {message}")
        self.action_id = action_id
        self.cause = cause


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _triggering_user() -> str:
    return os.environ.get("USER") or os.environ.get("USERNAME") or "agent"


def _load_action_type(workspace: Path, action_id: str) -> ActionType:
    path = workspace / "ontology" / "actionTypes" / f"{action_id}.yaml"
    if not path.is_file():
        raise ActionNotFoundError(f"ActionType not found: {action_id} (expected {path})")
    data = yaml.safe_load(path.read_text())
    return ActionType.model_validate(data)


def _substitute_command(template: str, args: dict[str, Any]) -> str:
    """Replace Jinja-style ``{{ name }}`` placeholders with argument values."""
    py_template = re.sub(r"\{\{\s*(\w+)\s*\}\}", r"{\1}", template)

    class _SafeDict(dict[str, Any]):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return py_template.format_map(_SafeDict(args))


def _write_audit(
    workspace: Path,
    action_id: str,
    *,
    status: str,
    command: str,
    dry_run: bool,
    args: dict[str, Any],
    error: str | None = None,
    driver_result: dict[str, Any] | None = None,
) -> Path:
    audit_dir = workspace / "ontology" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    audit_path = audit_dir / f"{ts}--{action_id}.json"
    payload: dict[str, Any] = {
        "timestamp": _utcnow_iso(),
        "triggering_user": _triggering_user(),
        "action_id": action_id,
        "status": status,
        "command": command,
        "dry_run": dry_run,
        "args": args,
    }
    if error is not None:
        payload["error"] = error
    if driver_result is not None:
        payload["driver_result"] = driver_result
    audit_path.write_text(json.dumps(payload, indent=2) + "\n")
    return audit_path


def _evaluate_success_predicate(
    predicate: str | None, args: dict[str, Any], driver_success: bool
) -> bool:
    if not predicate:
        return driver_success
    # v1: treat success_predicate as satisfied when the driver succeeded.
    return driver_success


def apply_action(
    workspace: Path,
    action_id: str,
    args: dict[str, Any] | None = None,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Load an ActionType, substitute args into its command template, and execute."""
    action_args = dict(args or {})
    action_type = _load_action_type(workspace, action_id)
    spec = action_type.spec or {}
    invocation = spec.get("invocation") or {}
    command_template = invocation.get("command", "")
    substituted = _substitute_command(command_template, action_args) if command_template else ""

    if dry_run:
        _write_audit(
            workspace,
            action_id,
            status="dry_run",
            command=substituted,
            dry_run=True,
            args=action_args,
        )
        return {"action": action_id, "command": substituted, "would_run": True}

    side_effects = spec.get("side_effects") or []
    if not side_effects:
        raise ActionExecutionError(action_id, "ActionType has no side_effects declared")

    side_effect = side_effects[0]
    kind = side_effect.get("kind", "")
    try:
        driver = get_driver(kind, side_effect=side_effect)
        result = driver.execute(substituted, action_args, dry_run=False)
    except (DriverNotFoundError, DriverAuthError, DriverUnavailableError) as exc:
        _write_audit(
            workspace,
            action_id,
            status="failed",
            command=substituted,
            dry_run=False,
            args=action_args,
            error=str(exc),
        )
        raise ActionExecutionError(action_id, str(exc), cause=exc) from exc

    success_predicate = invocation.get("success_predicate")
    ok = _evaluate_success_predicate(success_predicate, action_args, result.success)
    driver_payload = {
        "success": result.success,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command_run": result.command_run,
        "duration_ms": result.duration_ms,
    }

    if not ok:
        _write_audit(
            workspace,
            action_id,
            status="failed",
            command=substituted,
            dry_run=False,
            args=action_args,
            error="success_predicate not satisfied",
            driver_result=driver_payload,
        )
        raise ActionExecutionError(action_id, "success_predicate not satisfied")

    _write_audit(
        workspace,
        action_id,
        status="succeeded",
        command=substituted,
        dry_run=False,
        args=action_args,
        driver_result=driver_payload,
    )
    return {
        "action": action_id,
        "command": substituted,
        "would_run": False,
        "success": True,
        "driver_result": driver_payload,
    }
