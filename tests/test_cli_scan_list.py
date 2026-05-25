import json
import os
import site
import subprocess
import sys
from pathlib import Path


def _src_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src"


def _subprocess_env(tmp_home: Path) -> dict[str, str]:
    """Subprocess env that overrides HOME (for scan-dir isolation) but
    keeps user-site dependencies resolvable by pinning PYTHONUSERBASE
    to the real one."""
    user_base = os.environ.get(
        "PYTHONUSERBASE",
        str(Path(site.getuserbase()).resolve()),
    )
    return {
        **os.environ,
        "HOME": str(tmp_home),
        "PYTHONUSERBASE": user_base,
        "PYTHONPATH": str(_src_root()),
    }


def test_scan_list_json_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    out = subprocess.check_output(
        [sys.executable, "-m", "agent_readiness.cli", "scan-list", "--json"],
        env=_subprocess_env(tmp_path),
    )
    data = json.loads(out)
    assert data == {"active": [], "recent": [], "total_disk_bytes": 0}


def test_scan_stop_all_handles_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    out = subprocess.check_output(
        [sys.executable, "-m", "agent_readiness.cli", "scan-stop", "--all"],
        env=_subprocess_env(tmp_path),
    )
    assert b"Stopped 0" in out
