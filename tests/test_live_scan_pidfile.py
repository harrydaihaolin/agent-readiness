import json
import os

from agent_readiness.live_scan.pidfile import (
    PidStatus,
    clear_pidfile,
    verify_pidfile,
    write_pidfile,
)


def test_write_pidfile_emits_json_with_three_fields(tmp_path):
    pf = tmp_path / "daemon.pid"
    write_pidfile(pf, scan_id="mle-a3f2c1")
    data = json.loads(pf.read_text())
    assert data["pid"] == os.getpid()
    assert data["scan_id"] == "mle-a3f2c1"
    assert isinstance(data["started_at"], (int, float))


def test_verify_pidfile_returns_live_for_current_process(tmp_path):
    pf = tmp_path / "daemon.pid"
    write_pidfile(pf, scan_id="x")
    assert verify_pidfile(pf) is PidStatus.LIVE


def test_verify_pidfile_returns_stale_for_dead_pid(tmp_path):
    pf = tmp_path / "daemon.pid"
    pf.write_text(json.dumps(
        {"pid": 99999999, "started_at": 1700000000.0, "scan_id": "x"}
    ))
    assert verify_pidfile(pf) is PidStatus.STALE


def test_verify_pidfile_returns_recycled_when_starttime_mismatches(tmp_path):
    pf = tmp_path / "daemon.pid"
    pf.write_text(json.dumps(
        {"pid": os.getpid(), "started_at": 0.0, "scan_id": "x"}
    ))
    assert verify_pidfile(pf) is PidStatus.RECYCLED


def test_verify_pidfile_returns_missing_when_file_absent(tmp_path):
    assert verify_pidfile(tmp_path / "nope.pid") is PidStatus.MISSING


def test_clear_pidfile_removes_file(tmp_path):
    pf = tmp_path / "daemon.pid"
    pf.write_text("{}")
    clear_pidfile(pf)
    assert not pf.exists()


def test_clear_pidfile_is_idempotent(tmp_path):
    clear_pidfile(tmp_path / "nope.pid")
