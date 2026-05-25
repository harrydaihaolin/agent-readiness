import json
import os

from agent_readiness.live_scan.discovery import list_scans


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


def test_list_scans_skips_pidfile_with_recycled_stamp(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sd = tmp_path / ".agent-readiness" / "scans" / "ws-cccccc"
    sd.mkdir(parents=True)
    (sd / "daemon.pid").write_text(json.dumps({
        "pid": os.getpid(), "started_at": 0.0, "scan_id": "ws-cccccc"
    }))
    result = list_scans()
    assert result["active"] == []
