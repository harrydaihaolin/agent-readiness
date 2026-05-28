import json
import os
import site
import subprocess
import sys
from pathlib import Path


def _make_workspace(root: Path, *, repos: list[str]) -> Path:
    ws = root / "ws"
    ws.mkdir()
    for r in repos:
        d = ws / r
        d.mkdir()
        (d / ".git").mkdir()
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
        "PYTHONPATH": os.pathsep.join(
            dict.fromkeys([
                str(Path(__file__).resolve().parents[1] / "src"),
                *sys.path,
            ])
        ),
    }


def test_cli_scan_and_view_writes_onboarding_json(tmp_path, monkeypatch):
    """v4.0.0: scan-and-view is a deprecation shim that opens onboarding."""
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = _make_workspace(tmp_path, repos=["a", "b"])
    proc = subprocess.run(
        [
            sys.executable, "-m", "agent_readiness.cli", "scan-and-view",
            str(ws),
            "--json",
            "--no-open",
        ],
        env=_subprocess_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "onboarding_required"
    from agent_readiness.onboarding import load, path_for
    state = load(path_for(payload["scan_id"]))
    assert state is not None
    assert state.committed_type == "workspace"


def test_cli_scan_and_view_echoes_onboarding_dashboard_url(tmp_path, monkeypatch):
    """Regression: deprecation shim must return /#/onboarding/<scan_id> URL."""
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = _make_workspace(tmp_path, repos=["a"])
    proc = subprocess.run(
        [
            sys.executable, "-m", "agent_readiness.cli", "scan-and-view",
            str(ws),
            "--json",
            "--no-open",
        ],
        env=_subprocess_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "/#/onboarding/" in payload["dashboard_url"]
    assert "deprecated" in proc.stderr.lower()
