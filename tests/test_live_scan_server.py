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
