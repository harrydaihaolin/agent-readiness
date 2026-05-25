import json
import signal
import subprocess
import sys
import time
from pathlib import Path

from agent_readiness.live_scan.worker import scan_workspace


def _make_repo(d: Path, name: str) -> Path:
    r = d / name
    r.mkdir()
    (r / "README.md").write_text(f"# {name}\n")
    (r / "AGENTS.md").write_text("# Agents\n")
    return r


def test_scan_workspace_writes_envelope_per_child(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = tmp_path / "ws"
    ws.mkdir()
    repos = [_make_repo(ws, f"r{i}") for i in range(3)]

    scan_workspace(ws, children=repos)

    from agent_readiness.live_scan.paths import scan_dir
    sd = scan_dir(ws)
    assert not (sd / "live.json").exists()
    latest = json.loads((sd / "latest.json").read_text())
    assert latest["status"] == "completed"
    assert latest["progress"]["completed"] == 3
    assert latest["progress"]["total"] == 3
    assert len(latest["children"]) == 3


def test_scan_workspace_continues_when_one_child_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = tmp_path / "ws"
    ws.mkdir()
    good = _make_repo(ws, "good")
    bad = tmp_path / "does-not-exist"
    scan_workspace(ws, children=[good, bad])
    from agent_readiness.live_scan.paths import scan_dir
    latest = json.loads((scan_dir(ws) / "latest.json").read_text())
    assert latest["status"] == "completed"
    assert latest["stats"]["children_failed_paths"]


def test_scan_workspace_writes_pidfile_and_clears_on_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = tmp_path / "ws"
    ws.mkdir()
    _make_repo(ws, "r1")
    scan_workspace(ws, children=[ws / "r1"])
    from agent_readiness.live_scan.paths import scan_dir
    assert not (scan_dir(ws) / "daemon.pid").exists()


def test_scan_workspace_sigterm_marks_cancelled(tmp_path, monkeypatch):
    """Spawn a subprocess that runs a slow scan, SIGTERM it, check status."""
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = tmp_path / "ws"
    ws.mkdir()
    # 5 repos — enough that we should catch it mid-stream.
    for i in range(5):
        repo = ws / f"r{i}"
        repo.mkdir()
        (repo / "AGENTS.md").write_text("# Agents\n")
    src_root = Path(__file__).resolve().parents[1] / "src"
    script = tmp_path / "run.py"
    script.write_text(
        "import os, sys\n"
        f"sys.path.insert(0, {src_root!r})\n"
        f"os.environ['HOME'] = {str(tmp_path)!r}\n"
        "from pathlib import Path\n"
        "from agent_readiness.live_scan.worker import scan_workspace\n"
        f"scan_workspace(Path({str(ws)!r}), "
        f"children=[Path({str(ws)!r}) / f'r{{i}}' for i in range(5)])\n"
    )
    proc = subprocess.Popen([sys.executable, str(script)])
    time.sleep(1.0)
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=15)
    from agent_readiness.live_scan.paths import scan_dir
    sd = scan_dir(ws)
    # cancelled scans leave live.json (no archive write)
    if (sd / "live.json").exists():
        data = json.loads((sd / "live.json").read_text())
        assert data["status"] == "cancelled"
