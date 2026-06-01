import json
import urllib.error
import urllib.request

from agent_readiness.live_scan.server import dashboard_dist_path, start_server


def test_dashboard_dist_path_resolves_to_package_resource():
    p = dashboard_dist_path()
    assert p.is_dir()
    assert (p / "index.html").is_file()


def test_start_server_serves_dashboard_index(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    srv = start_server(host="127.0.0.1", port=0, data_dir=data_dir)
    try:
        url = f"http://{srv.host}:{srv.port}/"
        resp = urllib.request.urlopen(url, timeout=2)
        body = resp.read().decode()
        assert "agent-readiness" in body.lower()
    finally:
        srv.shutdown()


def test_start_server_serves_scan_json_from_live(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "live.json").write_text(json.dumps({"status": "in_progress"}))
    srv = start_server(host="127.0.0.1", port=0, data_dir=data_dir)
    try:
        url = f"http://{srv.host}:{srv.port}/data/scan.json"
        resp = urllib.request.urlopen(url, timeout=2)
        body = json.loads(resp.read().decode())
        assert body["status"] == "in_progress"
    finally:
        srv.shutdown()


def test_start_server_falls_back_to_latest(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "latest.json").write_text(json.dumps({"status": "completed"}))
    srv = start_server(host="127.0.0.1", port=0, data_dir=data_dir)
    try:
        url = f"http://{srv.host}:{srv.port}/data/scan.json"
        resp = urllib.request.urlopen(url, timeout=2)
        body = json.loads(resp.read().decode())
        assert body["status"] == "completed"
    finally:
        srv.shutdown()


def test_intents_create_list_claim_ack_over_http(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    srv = start_server(host="127.0.0.1", port=0, data_dir=data_dir)
    base = f"http://{srv.host}:{srv.port}"
    try:
        req = urllib.request.Request(
            f"{base}/api/intents",
            data=json.dumps({"action": "start", "path": "/abs/ws"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        created = json.loads(urllib.request.urlopen(req, timeout=2).read())
        iid = created["id"]
        assert created["status"] == "pending"

        listed = json.loads(urllib.request.urlopen(f"{base}/api/intents", timeout=2).read())
        assert any(r["id"] == iid for r in listed["intents"])

        creq = urllib.request.Request(f"{base}/api/intents/{iid}/claim", method="POST")
        claimed = json.loads(urllib.request.urlopen(creq, timeout=2).read())
        assert claimed["status"] == "claimed"

        areq = urllib.request.Request(
            f"{base}/api/intents/{iid}/ack",
            data=json.dumps({"status": "done", "result": {"dashboard_url": "http://x"}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        acked = json.loads(urllib.request.urlopen(areq, timeout=2).read())
        assert acked["status"] == "done"
    finally:
        srv.shutdown()


def test_intents_create_validation_returns_400(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    srv = start_server(host="127.0.0.1", port=0, data_dir=data_dir)
    base = f"http://{srv.host}:{srv.port}"
    try:
        req = urllib.request.Request(
            f"{base}/api/intents",
            data=json.dumps({"action": "start"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=2)
            raise AssertionError("expected HTTPError 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        srv.shutdown()


def test_start_server_serves_workspaces_index(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # One completed scan on this machine → one workspace in the index.
    sd = tmp_path / ".agent-readiness" / "scans" / "ws-zzzzzz"
    sd.mkdir(parents=True)
    (sd / "latest.json").write_text(json.dumps({
        "status": "completed",
        "overall_score": 91.0,
        "repo_path": "/abs/demo",
        "completed_at": "2026-05-27T00:00:00+00:00",
    }))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    srv = start_server(host="127.0.0.1", port=0, data_dir=data_dir)
    try:
        url = f"http://{srv.host}:{srv.port}/api/workspaces"
        body = json.loads(urllib.request.urlopen(url, timeout=2).read().decode())
        assert body["schema"] == 1
        assert len(body["workspaces"]) == 1
        assert body["workspaces"][0]["workspace_path"] == "/abs/demo"
        assert body["workspaces"][0]["trend_points"] == [91.0]
    finally:
        srv.shutdown()


def test_start_server_404_on_unknown_path(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    srv = start_server(host="127.0.0.1", port=0, data_dir=data_dir)
    try:
        url = f"http://{srv.host}:{srv.port}/nonsense-does-not-exist"
        try:
            urllib.request.urlopen(url, timeout=2)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()
