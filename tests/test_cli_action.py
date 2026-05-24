from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = {"PYTHONPATH": str(repo_root / "src"), **__import__("os").environ}
    return subprocess.run(
        [sys.executable, "-m", "agent_readiness.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd or repo_root,
        check=False,
    )


def test_cli_apply_action_dry_run(intent_workspace: Path):
    result = _run_cli(
        "ontology",
        "apply-action",
        str(intent_workspace),
        "--action-id",
        "publish.pypi",
        "--arg",
        "sdist=dist/foo.whl",
        "--json",
        cwd=intent_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["would_run"] is True
    assert payload["command"] == "twine upload dist/foo.whl"


def test_cli_record_intent(intent_workspace: Path):
    result = _run_cli(
        "ontology",
        "record-intent",
        str(intent_workspace),
        "--intent-type",
        "test_release",
        "--goal-arg",
        "repo=repo-a",
        "--started-by",
        "cli-user",
        "--json",
        cwd=intent_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["intent_type"] == "test_release"
    assert payload["status"] == "pending"


def test_cli_advance_intent(intent_workspace: Path):
    recorded = _run_cli(
        "ontology",
        "record-intent",
        str(intent_workspace),
        "--intent-type",
        "test_release",
        "--goal-arg",
        "repo=repo-a",
        "--json",
        cwd=intent_workspace,
    )
    intent_id = json.loads(recorded.stdout)["intent_id"]
    result = _run_cli(
        "ontology",
        "advance-intent",
        str(intent_workspace),
        "--intent-id",
        intent_id,
        "--step-id",
        "tag_repo",
        "--json",
        cwd=intent_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "committed"


def test_cli_query_intent(intent_workspace: Path):
    recorded = _run_cli(
        "ontology",
        "record-intent",
        str(intent_workspace),
        "--intent-type",
        "test_release",
        "--goal-arg",
        "repo=repo-a",
        "--json",
        cwd=intent_workspace,
    )
    intent_id = json.loads(recorded.stdout)["intent_id"]
    result = _run_cli(
        "ontology",
        "query-intent",
        str(intent_workspace),
        "--intent-id",
        intent_id,
        "--json",
        cwd=intent_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "in_progress"


def test_cli_list_active_intents(intent_workspace: Path):
    _run_cli(
        "ontology",
        "record-intent",
        str(intent_workspace),
        "--intent-type",
        "test_release",
        "--goal-arg",
        "repo=repo-a",
        "--json",
        cwd=intent_workspace,
    )
    result = _run_cli(
        "ontology",
        "list-active-intents",
        str(intent_workspace),
        "--json",
        cwd=intent_workspace,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert len(payload) >= 1


def test_cli_ontology_help_lists_action_verbs():
    result = _run_cli("ontology", "--help")
    assert result.returncode == 0
    for verb in (
        "apply-action",
        "record-intent",
        "advance-intent",
        "query-intent",
        "list-active-intents",
    ):
        assert verb in result.stdout
