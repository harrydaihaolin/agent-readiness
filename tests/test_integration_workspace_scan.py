import json
import os
import site
import subprocess
import sys
import time
from pathlib import Path


FIXTURE_WS = Path(__file__).parent / "fixtures/workspaces/small"


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


def test_end_to_end_live_scan_matches_headless_scoring(tmp_path, monkeypatch):
    """End-to-end: scan-and-view should produce the same scores as workspace-scan."""
    monkeypatch.setenv("HOME", str(tmp_path))
    children = sorted(p for p in FIXTURE_WS.iterdir() if p.is_dir())
    children_csv = ",".join(str(c) for c in children)

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "agent_readiness.cli", "scan-and-view",
            str(FIXTURE_WS), "--children", children_csv, "--no-open",
            "--idle-timeout-s", "1",
        ],
        env=_subprocess_env(tmp_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        from agent_readiness.live_scan.paths import scan_dir
        sd = scan_dir(FIXTURE_WS)
        deadline = time.monotonic() + 60
        latest = sd / "latest.json"
        while time.monotonic() < deadline:
            if latest.exists():
                data = json.loads(latest.read_text())
                if data.get("status") == "completed":
                    break
            time.sleep(0.5)
        assert latest.exists()
        live_data = json.loads(latest.read_text())
        assert live_data["status"] == "completed"
        assert live_data["progress"]["completed"] == 3
        # Compare against headless workspace-scan envelope.
        headless = subprocess.check_output(
            [
                sys.executable, "-m", "agent_readiness.cli", "workspace-scan",
                str(FIXTURE_WS), "--children", children_csv, "--json",
            ],
            env=_subprocess_env(tmp_path),
        )
        headless_data = json.loads(headless)
        assert abs(
            live_data["overall_score"] - headless_data["overall_score"]
        ) < 0.01
        # Headless envelope shape uses ``pillars`` list of dicts;
        # convert to a flat name→score map for comparison.
        headless_pillars = {
            p["pillar"]: p["score"] for p in headless_data["pillars"]
        }
        for name, score in headless_pillars.items():
            assert abs(live_data["pillar_scores"][name] - score) < 0.01
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
