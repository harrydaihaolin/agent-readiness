import os
import site
import subprocess
import sys
import time
from pathlib import Path


def _make_workspace(root: Path, *, repos: list[str]) -> Path:
    ws = root / "ws"
    ws.mkdir()
    for r in repos:
        d = ws / r
        d.mkdir()
        (d / "AGENTS.md").write_text(f"# {r}\n")
    return ws


def _subprocess_env(tmp_home: Path) -> dict[str, str]:
    user_base = os.environ.get(
        "PYTHONUSERBASE",
        str(Path(site.getuserbase()).resolve()),
    )
    return {
        **os.environ,
        "HOME": str(tmp_home),
        "PYTHONUSERBASE": user_base,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
    }


def test_cli_scan_and_view_writes_server_url_and_pidfile(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = _make_workspace(tmp_path, repos=["a", "b", "c"])
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "agent_readiness.cli", "scan-and-view",
            str(ws),
            "--children", f"{ws / 'a'},{ws / 'b'},{ws / 'c'}",
            "--no-open",
            "--idle-timeout-s", "1",
        ],
        env=_subprocess_env(tmp_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    from agent_readiness.live_scan.paths import scan_dir
    sd = scan_dir(ws)
    url_file = sd / "server.url"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if url_file.exists():
            break
        time.sleep(0.1)
    try:
        assert url_file.exists()
        assert url_file.read_text().strip().startswith("http://")
        assert (sd / "daemon.pid").exists()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
