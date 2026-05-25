import json
import os
import site
import subprocess
import sys
from pathlib import Path


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


def test_render_report_emits_index_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan.paths import scan_dir
    ws = tmp_path / "ws"
    ws.mkdir()
    sd = scan_dir(ws)
    sd.mkdir(parents=True)
    (sd / "latest.json").write_text(
        json.dumps({"status": "completed", "overall_score": 50})
    )
    out_dir = tmp_path / "report"
    res = subprocess.check_output(
        [
            sys.executable, "-m", "agent_readiness.cli", "render-report",
            str(ws),
            "--output-dir", str(out_dir),
            "--json",
        ],
        env=_subprocess_env(tmp_path),
    )
    data = json.loads(res)
    assert Path(data["index_path"]).exists()
    assert data["source_status"] == "completed"
