from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_readiness.ontology.runtime import ActionNotFoundError, apply_action


def test_apply_action_dry_run_writes_audit(action_workspace: Path):
    result = apply_action(
        action_workspace,
        "publish.pypi",
        {"sdist": "dist/foo.tar.gz"},
        dry_run=True,
    )
    assert result["would_run"] is True
    assert result["command"] == "twine upload dist/foo.tar.gz"

    audit_dir = action_workspace / "ontology" / "audit"
    audit_files = list(audit_dir.glob("*--publish.pypi.json"))
    assert len(audit_files) == 1
    payload = json.loads(audit_files[0].read_text())
    assert payload["status"] == "dry_run"
    assert payload["dry_run"] is True
    assert payload["command"] == "twine upload dist/foo.tar.gz"


def test_apply_action_unknown_action_id(action_workspace: Path):
    with pytest.raises(ActionNotFoundError):
        apply_action(action_workspace, "missing.action", {}, dry_run=True)


def test_apply_action_with_args_substitutes_command(action_workspace: Path):
    result = apply_action(
        action_workspace,
        "publish.pypi",
        {"sdist": "dist/custom.whl"},
        dry_run=True,
    )
    assert result["action"] == "publish.pypi"
    assert result["command"] == "twine upload dist/custom.whl"
