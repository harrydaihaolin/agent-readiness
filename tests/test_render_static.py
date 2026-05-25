import json

import pytest

from agent_readiness.render import export_report


def test_export_report_uses_latest_when_no_scan_id(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan.paths import scan_dir
    ws = tmp_path / "ws"
    ws.mkdir()
    sd = scan_dir(ws)
    sd.mkdir(parents=True)
    (sd / "latest.json").write_text(
        json.dumps({"status": "completed", "overall_score": 80.0})
    )
    out = tmp_path / "out"
    result = export_report(ws, output_dir=out)
    assert result.index_path == out / "index.html"
    assert (out / "data" / "scan.json").exists()
    body = (out / "index.html").read_text()
    assert "window.__SCAN_ENVELOPE__" in body
    assert '"overall_score": 80.0' in body


def test_export_report_uses_live_when_present(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan.paths import scan_dir
    ws = tmp_path / "ws"
    ws.mkdir()
    sd = scan_dir(ws)
    sd.mkdir(parents=True)
    (sd / "latest.json").write_text(
        json.dumps({"status": "completed", "overall_score": 80.0})
    )
    (sd / "live.json").write_text(
        json.dumps({"status": "in_progress", "overall_score": None})
    )
    result = export_report(ws, output_dir=tmp_path / "out")
    assert result.source_status == "in_progress"


def test_export_report_raises_when_no_history(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(FileNotFoundError):
        export_report(ws, output_dir=tmp_path / "out")


def test_export_report_copies_dashboard_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan.paths import scan_dir
    ws = tmp_path / "ws"
    ws.mkdir()
    sd = scan_dir(ws)
    sd.mkdir(parents=True)
    (sd / "latest.json").write_text(json.dumps({"status": "completed"}))
    out = tmp_path / "out"
    export_report(ws, output_dir=out)
    assert (out / "index.html").exists()
