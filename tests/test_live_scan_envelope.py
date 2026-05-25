import json
import os
from pathlib import Path

from agent_readiness.live_scan.envelope import (
    add_completed_child,
    atomic_write_json,
    new_envelope,
    set_in_flight,
    set_status,
    write_envelope,
)


def test_atomic_write_creates_file(tmp_path):
    target = tmp_path / "data.json"
    atomic_write_json(target, {"x": 1})
    assert json.loads(target.read_text()) == {"x": 1}


def test_atomic_write_overwrites_existing(tmp_path):
    target = tmp_path / "data.json"
    target.write_text('{"x": 0}')
    atomic_write_json(target, {"x": 99})
    assert json.loads(target.read_text()) == {"x": 99}


def test_atomic_write_cleans_up_tmp_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "data.json"
    real_replace = os.replace

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    try:
        atomic_write_json(target, {"x": 1})
    except OSError:
        pass
    monkeypatch.setattr(os, "replace", real_replace)
    assert list(tmp_path.glob("*.tmp")) == []


def test_new_envelope_has_required_fields(tmp_path):
    ws = tmp_path / "mle"
    ws.mkdir()
    env = new_envelope(ws, total_children=42)
    assert env["schema"] == 1
    assert env["status"] == "in_progress"
    assert env["progress"] == {"completed": 0, "total": 42, "in_flight": []}
    assert env["started_at"]
    assert env["completed_at"] is None
    assert env["repo_path"] == str(ws.resolve())
    assert env["overall_score"] is None
    assert env["pillar_scores"] == {}
    assert env["children"] == []


def test_set_in_flight_replaces_list():
    env = {"progress": {"completed": 0, "total": 5, "in_flight": ["/a"]}}
    set_in_flight(env, [Path("/b"), Path("/c")])
    assert env["progress"]["in_flight"] == ["/b", "/c"]


def test_add_completed_child_increments_and_appends():
    env = {
        "progress": {"completed": 0, "total": 5, "in_flight": ["/a"]},
        "children": [],
    }
    add_completed_child(env, {"path": "/a", "overall_score": 80.0})
    assert env["progress"]["completed"] == 1
    assert env["progress"]["in_flight"] == []
    assert env["children"][0] == {"path": "/a", "overall_score": 80.0}


def test_set_status_terminal_sets_completed_at():
    env = {"status": "in_progress", "completed_at": None}
    set_status(env, "completed")
    assert env["status"] == "completed"
    assert env["completed_at"]


def test_write_envelope_creates_live_json(tmp_path):
    write_envelope(tmp_path, {"status": "in_progress"})
    assert (tmp_path / "live.json").exists()
    assert json.loads((tmp_path / "live.json").read_text())["status"] == "in_progress"
