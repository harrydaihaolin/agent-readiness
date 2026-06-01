"""Detached dashboard server: must outlive the process that launches it.

Regression coverage for the bug where ``_launch_dashboard_with_onboarding``
started the HTTP server on an in-process daemon thread, so the socket died
the instant the short-lived CLI process exited and the advertised
``dashboard_url`` was never reachable.
"""
import json
import os
import signal
import urllib.request

import pytest

from agent_readiness.live_scan.pidfile import PidStatus, verify_pidfile
from agent_readiness.live_scan.server import start_detached_server


def _kill(data_dir):
    pid_file = data_dir / "server.pid"
    if pid_file.exists():
        try:
            os.kill(json.loads(pid_file.read_text())["pid"], signal.SIGTERM)
        except (ProcessLookupError, KeyError, json.JSONDecodeError):
            pass


def test_detached_server_runs_in_a_separate_surviving_process(tmp_path):
    data_dir = tmp_path / "scan"
    data_dir.mkdir()
    base = start_detached_server(data_dir=data_dir, workspace_path=tmp_path)
    try:
        # The base URL is reachable: the socket is bound and stays bound
        # even though the call that started it has already returned.
        resp = urllib.request.urlopen(base + "/", timeout=3)
        assert "agent-readiness" in resp.read().decode().lower()

        # It is served by a DIFFERENT, live process — not this one. That
        # is what lets it survive the caller exiting.
        pid = json.loads((data_dir / "server.pid").read_text())["pid"]
        assert pid != os.getpid()
        assert verify_pidfile(data_dir / "server.pid") is PidStatus.LIVE
    finally:
        _kill(data_dir)


def test_detached_server_writes_server_url_matching_return(tmp_path):
    data_dir = tmp_path / "scan"
    data_dir.mkdir()
    base = start_detached_server(data_dir=data_dir, workspace_path=tmp_path)
    try:
        assert (data_dir / "server.url").read_text().strip() == base
        assert base.startswith("http://127.0.0.1:")
    finally:
        _kill(data_dir)


def test_detached_server_is_idempotent_for_a_live_scan_dir(tmp_path):
    data_dir = tmp_path / "scan"
    data_dir.mkdir()
    base1 = start_detached_server(data_dir=data_dir, workspace_path=tmp_path)
    try:
        pid1 = json.loads((data_dir / "server.pid").read_text())["pid"]
        # Second call against a scan dir whose server is already live must
        # reuse it, not spawn a second listener on a new port.
        base2 = start_detached_server(data_dir=data_dir, workspace_path=tmp_path)
        pid2 = json.loads((data_dir / "server.pid").read_text())["pid"]
        assert base2 == base1
        assert pid2 == pid1
    finally:
        _kill(data_dir)


def test_detached_server_times_out_if_never_ready(tmp_path, monkeypatch):
    data_dir = tmp_path / "scan"
    data_dir.mkdir()

    # Force the spawn to be a no-op so server.url never appears, proving
    # the parent surfaces a clear timeout rather than hanging forever.
    import agent_readiness.live_scan.server as server_mod

    monkeypatch.setattr(server_mod.subprocess, "Popen", lambda *a, **k: None)
    with pytest.raises(TimeoutError):
        start_detached_server(
            data_dir=data_dir, workspace_path=tmp_path, ready_timeout_s=0.5
        )
