import json
import os

from agent_readiness.live_scan.discovery import build_workspace_index, list_scans


def _write_completed(tmp_path, scan_id, *, ws, score, completed_at):
    sd = tmp_path / ".agent-readiness" / "scans" / scan_id
    sd.mkdir(parents=True)
    (sd / "latest.json").write_text(json.dumps({
        "status": "completed",
        "overall_score": score,
        "repo_path": ws,
        "completed_at": completed_at,
    }))
    return sd


def test_list_scans_empty_when_no_workspaces(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = list_scans()
    assert result == {"active": [], "recent": [], "total_disk_bytes": 0}


def test_list_scans_finds_recent_completed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sd = tmp_path / ".agent-readiness" / "scans" / "ws-aaaaaa"
    sd.mkdir(parents=True)
    (sd / "latest.json").write_text(json.dumps({
        "status": "completed",
        "overall_score": 67.4,
        "repo_path": "/abs/ws",
        "completed_at": "2026-05-25T14:30:12+00:00",
    }))
    result = list_scans()
    assert len(result["recent"]) == 1
    assert result["recent"][0]["overall_score"] == 67.4
    assert result["total_disk_bytes"] > 0


def test_list_scans_distinguishes_active(tmp_path, monkeypatch):
    """daemon.pid must verify as LIVE for an entry to be 'active'."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sd = tmp_path / ".agent-readiness" / "scans" / "ws-bbbbbb"
    sd.mkdir(parents=True)
    (sd / "live.json").write_text(json.dumps({
        "status": "in_progress",
        "progress": {"completed": 3, "total": 8, "in_flight": []},
        "repo_path": "/abs/ws",
    }))
    from agent_readiness.live_scan.pidfile import write_pidfile
    write_pidfile(sd / "daemon.pid", scan_id="ws-bbbbbb")
    (sd / "server.url").write_text("http://localhost:12345\n")
    result = list_scans()
    assert len(result["active"]) == 1
    assert result["active"][0]["dashboard_url"] == "http://localhost:12345"


def test_build_workspace_index_groups_completed_scans_into_a_trend(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # Two completed scans of the SAME workspace, oldest first on disk.
    _write_completed(tmp_path, "ws-old", ws="/abs/ws", score=67.4,
                     completed_at="2026-05-25T14:00:00+00:00")
    _write_completed(tmp_path, "ws-new", ws="/abs/ws", score=80.1,
                     completed_at="2026-05-26T14:00:00+00:00")

    idx = build_workspace_index()

    assert idx["schema"] == 1
    assert "generated_at" in idx
    assert len(idx["workspaces"]) == 1
    ws = idx["workspaces"][0]
    assert ws["workspace_path"] == "/abs/ws"
    # trend_points oldest-first
    assert ws["trend_points"] == [67.4, 80.1]
    # headline fields reflect the latest scan
    assert ws["overall_score"] == 80.1
    assert ws["scan_id"] == "ws-new"
    assert ws["status"] == "completed"
    # delta = latest - prior
    assert round(ws["delta"], 1) == 12.7


def test_build_workspace_index_orders_workspaces_newest_first(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_completed(tmp_path, "alpha", ws="/abs/alpha", score=90.0,
                     completed_at="2026-05-20T00:00:00+00:00")
    _write_completed(tmp_path, "bravo", ws="/abs/bravo", score=50.0,
                     completed_at="2026-05-28T00:00:00+00:00")

    idx = build_workspace_index()
    paths = [w["workspace_path"] for w in idx["workspaces"]]
    assert paths == ["/abs/bravo", "/abs/alpha"]


def test_build_workspace_index_empty_when_no_scans(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    idx = build_workspace_index()
    assert idx["schema"] == 1
    assert idx["workspaces"] == []
    assert idx["active"] == []


def test_list_scans_skips_pidfile_with_recycled_stamp(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sd = tmp_path / ".agent-readiness" / "scans" / "ws-cccccc"
    sd.mkdir(parents=True)
    (sd / "daemon.pid").write_text(json.dumps({
        "pid": os.getpid(), "started_at": 0.0, "scan_id": "ws-cccccc"
    }))
    result = list_scans()
    assert result["active"] == []
