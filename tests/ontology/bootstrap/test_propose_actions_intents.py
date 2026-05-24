from __future__ import annotations

from pathlib import Path

import pytest

from agent_readiness.ontology.bootstrap.propose_actions_intents import (
    propose_action_intent_types,
)

from .conftest import write_ratified_repo_instance


@pytest.fixture
def workspace_with_publish_workflow(tmp_path: Path) -> Path:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "release.yml").write_text(
        "name: release\non: push\njobs:\n  publish:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: twine upload dist/*\n"
    )
    write_ratified_repo_instance(tmp_path, "myrepo")
    return tmp_path


def test_proposes_publish_pypi_from_twine_upload(workspace_with_publish_workflow: Path):
    env = propose_action_intent_types(workspace_with_publish_workflow, scope="single_system")
    ids = {p.id for p in env.proposed}
    assert "publish.pypi" in ids
    assert (workspace_with_publish_workflow / "ontology" / "actionTypes" / "publish.pypi.yaml").is_file()


def test_proposes_intent_templates_when_scope_cross_repo(tmp_path: Path):
    env = propose_action_intent_types(tmp_path, scope="cross_repo")
    ids = {p.id for p in env.proposed}
    assert {"release_cascade", "deprecate_repo", "protocol_breaking_change"} <= ids
    for name in ("release_cascade", "deprecate_repo", "protocol_breaking_change"):
        assert (tmp_path / "ontology" / "intentTypes" / f"{name}.yaml").is_file()


def test_skips_existing_intent_files(tmp_path: Path):
    intents_dir = tmp_path / "ontology" / "intentTypes"
    intents_dir.mkdir(parents=True)
    (intents_dir / "release_cascade.yaml").write_text("kind: IntentType\n")
    env = propose_action_intent_types(tmp_path, scope="cross_repo")
    skipped = [a.id for a in env.ambiguities]
    assert "release_cascade" in skipped


def test_unknown_scope_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown scope"):
        propose_action_intent_types(tmp_path, scope="bogus")
