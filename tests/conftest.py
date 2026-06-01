from __future__ import annotations

import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from agent_readiness_insights_protocol.ontology.types import (
    Lifecycle,
    LifecycleState,
    LinkInstance,
    ObjectInstance,
)

from tests.ontology.bootstrap.conftest import write_ratified_repo_instance


@pytest.fixture(autouse=True)
def _reap_detached_dashboard_servers(tmp_path: Path):
    """Terminate any detached dashboard servers a test spawned under its
    own ``tmp_path``.

    Integration tests that drive ``scan-*`` (which now starts a *detached*
    HTTP server that deliberately outlives the CLI) would otherwise leak a
    live process per test. Scoped strictly to the test's tmp_path so it can
    never touch a real server under the developer's home directory.
    """
    yield
    scans = tmp_path / ".agent-readiness" / "scans"
    for pid_file in scans.glob("*/server.pid"):
        try:
            os.kill(json.loads(pid_file.read_text())["pid"], signal.SIGTERM)
        except (ProcessLookupError, KeyError, ValueError, OSError):
            pass


def _ratified_lifecycle() -> Lifecycle:
    now = datetime.now(timezone.utc).isoformat()
    return Lifecycle(
        state=LifecycleState.RATIFIED,
        proposed_by="test",
        proposed_at=now,
        confidence=1.0,
        markers=[],
        ratified_by="test-human",
        ratified_at=now,
    )


def _write_repo_type(ont: Path) -> None:
    (ont / "objectTypes").mkdir(parents=True, exist_ok=True)
    (ont / "objectTypes" / "Repo.yaml").write_text(
        """\
apiVersion: agent-readiness.io/v1
kind: ObjectType
metadata:
  name: Repo
  description: A git repository participating in the workspace.
spec:
  properties:
    - { name: name, type: string, required: true }
"""
    )


def _write_depends_on_type(ont: Path) -> None:
    (ont / "linkTypes").mkdir(parents=True, exist_ok=True)
    (ont / "linkTypes" / "dependsOn.yaml").write_text(
        """\
apiVersion: agent-readiness.io/v1
kind: LinkType
metadata:
  name: dependsOn
spec:
  from: Repo
  to: Repo
"""
    )


def _write_versioned_interface(ont: Path) -> None:
    (ont / "interfaces").mkdir(parents=True, exist_ok=True)
    (ont / "interfaces" / "Versioned.yaml").write_text(
        """\
apiVersion: agent-readiness.io/v1
kind: InterfaceType
metadata:
  name: Versioned
  description: Repo exposes a semver in its primary manifest.
spec:
  satisfaction_proof:
    type: regex_match
    file: "{{ primary_manifest }}"
    pattern: 'version\\s*[=:]\\s*["\\'']?\\d+\\.\\d+\\.\\d+'
"""
    )


def _write_compute_dep_graph_type(ont: Path) -> None:
    (ont / "functions").mkdir(parents=True, exist_ok=True)
    (ont / "functions" / "compute_dep_graph.yaml").write_text(
        """\
apiVersion: agent-readiness.io/v1
kind: FunctionType
metadata:
  name: compute_dep_graph
  description: Return dependsOn edges across ratified Repos.
spec:
  inputs: []
  outputs:
    - name: dag
      type: "list[{from: ref[Repo], to: ref[Repo]}]"
  pure: true
"""
    )
    (ont / "functions" / "compute_dep_graph.py").write_text(
        "def compute_dep_graph(ontology_root, **kw):\n"
        "    from agent_readiness.ontology.loader import load_ontology\n"
        "    ont = load_ontology(ontology_root)\n"
        "    edges = []\n"
        "    for link in ont.link_instances.get('dependsOn', []):\n"
        "        edges.append({'from': link.spec['from']['id'], 'to': link.spec['to']['id']})\n"
        "    return edges\n"
    )
    (ont / "functions" / "missing_impl.yaml").write_text(
        """\
apiVersion: agent-readiness.io/v1
kind: FunctionType
metadata:
  name: missing_impl
spec:
  inputs: []
  outputs: []
"""
    )


def _write_repo_with_claims(workspace: Path, repo_id: str, claims: list[dict]) -> None:
    target = workspace / "ontology" / "instances" / "Repo" / f"{repo_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    inst = ObjectInstance(
        apiVersion="agent-readiness.io/v1",
        kind="ObjectInstance",
        metadata={"object_type": "Repo", "id": repo_id},
        spec={
            "properties": {"name": repo_id, "primary_manifest": "pyproject.toml"},
            "implements": claims,
        },
        lifecycle=_ratified_lifecycle(),
    )
    target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))


def _write_ratified_link(
    workspace: Path,
    link_id: str,
    from_id: str,
    to_id: str,
) -> None:
    target = workspace / "ontology" / "instances" / "dependsOn" / f"{link_id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    inst = LinkInstance(
        apiVersion="agent-readiness.io/v1",
        kind="LinkInstance",
        metadata={"link_type": "dependsOn", "id": link_id},
        spec={
            "from": {"object_type": "Repo", "id": from_id},
            "to": {"object_type": "Repo", "id": to_id},
        },
        lifecycle=_ratified_lifecycle(),
    )
    target.write_text(yaml.safe_dump(inst.model_dump(mode="json"), sort_keys=False))


@pytest.fixture
def runtime_workspace(tmp_path: Path) -> Path:
    """A workspace with a small ratified ontology suitable for runtime tests."""
    ont = tmp_path / "ontology"
    _write_repo_type(ont)
    _write_depends_on_type(ont)
    _write_versioned_interface(ont)
    _write_compute_dep_graph_type(ont)

    write_ratified_repo_instance(tmp_path, "repo-a")
    write_ratified_repo_instance(tmp_path, "repo-b")
    write_ratified_repo_instance(tmp_path, "repo-c")
    _write_repo_with_claims(
        tmp_path,
        "repo-a",
        [
            {
                "interface": "Versioned",
                "satisfaction": "ratified",
                "last_checked": "2026-05-24T00:00:00+00:00",
                "proof_refs": ["pyproject.toml"],
            }
        ],
    )
    _write_ratified_link(tmp_path, "a-deps-b", "repo-a", "repo-b")
    _write_ratified_link(tmp_path, "b-deps-c", "repo-b", "repo-c")
    return tmp_path


def _write_test_action_type(workspace: Path, action_id: str = "publish.pypi") -> None:
    action_dir = workspace / "ontology" / "actionTypes"
    action_dir.mkdir(parents=True, exist_ok=True)
    (action_dir / f"{action_id}.yaml").write_text(
        """\
apiVersion: agent-readiness.io/v1
kind: ActionType
metadata:
  name: publish.pypi
spec:
  scope: single_system
  side_effects:
    - kind: registry_write
      registry: pypi
      idempotent: false
  invocation:
    command: "twine upload {{ sdist }}"
    success_predicate: "pypi.has_version(package.name, version)"
"""
    )


def _write_test_intent_type(workspace: Path, intent_type: str = "test_release") -> None:
    intent_dir = workspace / "ontology" / "intentTypes"
    intent_dir.mkdir(parents=True, exist_ok=True)
    (intent_dir / f"{intent_type}.yaml").write_text(
        """\
apiVersion: agent-readiness.io/v1
kind: IntentType
metadata:
  name: test_release
spec:
  scope: cross_repo
  parameters:
    - name: repo
      type: ref[Repo]
      required: true
  steps:
    - id: tag_repo
      action: publish.pypi
      args:
        sdist: dist/repo-a.tar.gz
      preconditions:
        - object_id: repo-a
    - id: blocked_step
      action: publish.pypi
      args:
        sdist: dist/missing.tar.gz
      preconditions:
        - object_id: missing-repo
  ledger:
    location: ontology/intents/{{ intent_id }}.ledger.jsonl
    format: jsonl
"""
    )


@pytest.fixture
def action_workspace(runtime_workspace: Path) -> Path:
    _write_test_action_type(runtime_workspace)
    return runtime_workspace


@pytest.fixture
def intent_workspace(action_workspace: Path) -> Path:
    _write_test_intent_type(action_workspace)
    return action_workspace
