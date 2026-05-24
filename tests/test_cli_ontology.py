from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "ontology_minimal"


def test_ontology_load_emits_json():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_readiness.cli",
            "ontology",
            "load",
            str(FIXTURE / "ontology"),
            "--json",
        ],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": __import__("os").environ.get("PATH", "")},
        check=True,
    )
    payload = json.loads(result.stdout)
    assert "object_types" in payload
    assert "Repo" in payload["object_types"]
    assert payload["object_types"]["Repo"]["metadata"]["name"] == "Repo"


def test_ontology_load_empty_dir_exits_zero():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_readiness.cli",
            "ontology",
            "load",
            "/nonexistent/path/to/ontology",
            "--json",
        ],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src", "PATH": __import__("os").environ.get("PATH", "")},
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["object_types"] == {}
