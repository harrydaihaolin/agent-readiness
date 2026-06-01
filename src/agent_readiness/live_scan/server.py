"""Local HTTP server: serves packaged dashboard + scan data dir + SSE + JSON API.

Routing (in order):

    ``GET  /sse/scans/<id>``                        → SSE event stream (Bundle D)
    ``GET  /api/scans/<id>/snapshot``               → WorkspaceScanSnapshot JSON
    ``GET  /api/scans/<id>/topaction/diff``         → unified diff JSON
    ``POST /api/scans/<id>/prompts/<pid>/answer``   → submit prompt answer
    ``POST /api/scans/<id>/exit``                   → Exit-dashboard button
    ``POST /api/scans/<id>/topaction/apply``        → Apply-top-action button
    ``GET  /data/scan.json``                        → live.json or latest.json
    ``GET  /data/<other>``                          → ``<data_dir>/<other>``
    ``GET  /<other>``                               → packaged SPA dist
"""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Optional

from agent_readiness.live_scan import api as api_handlers
from agent_readiness.live_scan import sse as sse_handlers


def dashboard_dist_path() -> Path:
    """Return the absolute path to the packaged dashboard dist directory."""
    return Path(str(resources.files("agent_readiness") / "_dashboard_dist"))


@dataclass
class LiveServer:
    host: str
    port: int
    _httpd: socketserver.BaseServer = field(repr=False)
    _thread: threading.Thread = field(repr=False)

    def shutdown(self) -> None:
        self._httpd.shutdown()
        try:
            self._httpd.server_close()
        except Exception:
            pass
        self._thread.join(timeout=2)


def _make_handler(
    dist_dir: Path,
    data_dir: Path,
    workspace_path: Optional[Path] = None,
):
    """Build a request handler closed over the dist + data dir + workspace.

    ``workspace_path`` is required for snapshot building (the snapshot
    embeds the workspace_path field) and for top-action apply (the apply
    runs against that path). It can be omitted in tests that only
    exercise static-file serving.
    """
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(dist_dir), **kwargs)

        # ------------------------------------------------------------------
        # GET routing
        # ------------------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 — http.server contract
            # 1) SSE
            sse = api_handlers.parse_sse_path(self.path)
            if sse is not None:
                after = sse.get("since", -1)
                sse_handlers.handle_sse_request(self, data_dir, after_seq=after)
                return

            # 2) JSON GET API
            api = api_handlers.parse_api_path(self.path)
            if api is not None:
                if api["kind"] == "scans_list":
                    from agent_readiness.live_scan.onboarding_api import list_scans
                    body, status = list_scans()
                    api_handlers._send_json(self, status, body)
                    return
                if api["kind"] == "onboarding_get":
                    from agent_readiness.live_scan.onboarding_api import (
                        get_onboarding,
                        path_for_scan,
                    )
                    body, status = get_onboarding(path_for_scan(api["scan_id"]))
                    api_handlers._send_json(self, status, body)
                    return
                if api["kind"] == "snapshot":
                    if workspace_path is None:
                        self.send_error(503, "workspace_path not bound")
                        return
                    api_handlers.handle_snapshot_get(self, data_dir, workspace_path)
                    return
                if api["kind"] == "topaction_diff":
                    if workspace_path is None:
                        self.send_error(503, "workspace_path not bound")
                        return
                    api_handlers.handle_topaction_diff_get(self, data_dir, workspace_path)
                    return
                # POST-only kinds reaching GET → 405
                self.send_error(405, "method not allowed")
                return

            # 3) static (delegate to SimpleHTTPRequestHandler)
            super().do_GET()

        # ------------------------------------------------------------------
        # POST routing — entirely new (SimpleHTTPRequestHandler is GET-only)
        # ------------------------------------------------------------------

        def do_POST(self) -> None:  # noqa: N802
            api = api_handlers.parse_api_path(self.path)
            if api is None:
                self.send_error(404, "not found")
                return
            kind = api["kind"]
            if kind == "onboarding_commit":
                from agent_readiness.live_scan.onboarding_api import (
                    commit_onboarding,
                    path_for_scan,
                )
                body, status = commit_onboarding(
                    path_for_scan(api["scan_id"]),
                    request_body=api_handlers._read_json_body(self),
                )
                api_handlers._send_json(self, status, body)
                return
            if kind == "reconfigure":
                from agent_readiness.live_scan.onboarding_api import (
                    path_for_scan,
                    reconfigure_onboarding,
                )
                body, status = reconfigure_onboarding(path_for_scan(api["scan_id"]))
                api_handlers._send_json(self, status, body)
                return
            if kind == "exit":
                api_handlers.handle_exit_post(self, data_dir)
                return
            if kind == "prompt_answer":
                api_handlers.handle_prompt_answer_post(
                    self, data_dir, api["prompt_id"],
                )
                return
            if kind == "topaction_apply":
                if workspace_path is None:
                    self.send_error(503, "workspace_path not bound")
                    return
                api_handlers.handle_topaction_apply_post(
                    self, data_dir, api["scan_id"], workspace_path,
                )
                return
            self.send_error(405, "method not allowed")

        # ------------------------------------------------------------------
        # Existing static-path translation (kept verbatim)
        # ------------------------------------------------------------------

        def translate_path(self, path: str) -> str:
            if "?" in path:
                path = path.split("?", 1)[0]
            if "#" in path:
                path = path.split("#", 1)[0]
            if path in ("/data/scan.json",):
                live = data_dir / "live.json"
                latest = data_dir / "latest.json"
                return str(live if live.exists() else latest)
            if path == "/data" or path.startswith("/data/"):
                rel = path[len("/data"):].lstrip("/")
                return str(data_dir) if not rel else str(data_dir / rel)
            return super().translate_path(path)

        def log_message(self, format, *args):  # noqa: A002
            return

    return Handler


def start_server(
    *,
    host: str,
    port: int,
    data_dir: Path,
    workspace_path: Optional[Path] = None,
) -> LiveServer:
    """Start a ThreadingHTTPServer on a daemon thread. Returns immediately.

    ``workspace_path`` is optional for backward compatibility — callers
    that only need the static-file surface (older callers) can omit it.
    Bundle D's new SSE + JSON API surface needs it.
    """
    dist = dashboard_dist_path()
    handler = _make_handler(dist, Path(data_dir), workspace_path)
    httpd = http.server.ThreadingHTTPServer((host, port), handler)
    bound_host, bound_port = httpd.server_address[:2]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return LiveServer(host=bound_host, port=bound_port, _httpd=httpd, _thread=t)


def _atomic_write_text(path: Path, text: str) -> None:
    """Atomically write ``text`` to ``path`` (POSIX ``os.replace`` swap).

    ``server.url`` is the MCP wire-protocol handshake: a reader must never
    observe a half-written or truncated URL, hence the temp-then-rename.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _run_detached_server(spec_path: str) -> None:
    """Entrypoint for the detached server subprocess. Blocks forever.

    Binds the HTTP server, stamps ``server.pid`` so the daemon is
    discoverable/stoppable, then publishes ``server.url`` *last* — only
    once the socket is actually listening — and blocks so the process (and
    its socket) outlive the CLI invocation that spawned it.
    """
    from agent_readiness.live_scan.pidfile import write_pidfile

    spec = json.loads(Path(spec_path).read_text())
    data_dir = Path(spec["data_dir"])
    workspace = Path(spec["workspace"]) if spec.get("workspace") else None

    srv = start_server(
        host=spec["host"],
        port=spec["port"],
        data_dir=data_dir,
        workspace_path=workspace,
    )
    write_pidfile(data_dir / "server.pid", scan_id=data_dir.name)
    _atomic_write_text(
        data_dir / "server.url", f"http://{srv.host}:{srv.port}"
    )
    # Park the main thread; the server runs on srv's daemon thread.
    threading.Event().wait()


def start_detached_server(
    *,
    data_dir: Path,
    workspace_path: Optional[Path] = None,
    host: str = "127.0.0.1",
    port: int = 0,
    ready_timeout_s: float = 10.0,
) -> str:
    """Start a dashboard HTTP server that OUTLIVES the calling process.

    Unlike :func:`start_server` (a daemon thread that dies with the
    process), this spawns a detached, session-leader subprocess so the
    advertised ``dashboard_url`` stays reachable after a short-lived CLI
    invocation returns. Returns the base URL (``http://host:port``) once
    the child has bound its socket and published ``<data_dir>/server.url``.

    Idempotent: if the scan dir already has a live detached server, its
    existing base URL is returned instead of spawning a second listener.
    """
    from agent_readiness.live_scan.pidfile import PidStatus, verify_pidfile

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    url_file = data_dir / "server.url"
    pid_file = data_dir / "server.pid"

    if url_file.exists() and verify_pidfile(pid_file) is PidStatus.LIVE:
        return url_file.read_text().strip()

    # Drop any stale handshake so we never read a previous run's URL.
    url_file.unlink(missing_ok=True)

    spec_path = data_dir / ".server-job.json"
    spec_path.write_text(json.dumps({
        "data_dir": str(data_dir.resolve()),
        "workspace": str(workspace_path.resolve()) if workspace_path else None,
        "host": host,
        "port": port,
    }))

    src_root = str(Path(__file__).resolve().parents[2])
    runner = (
        f"import sys; sys.path.insert(0, {src_root!r}); "
        "from agent_readiness.live_scan.server import _run_detached_server; "
        "_run_detached_server(sys.argv[1])"
    )
    # Detach std streams to DEVNULL. If the child inherited our pipes, a
    # parent reading with subprocess.run(capture_output=True) — exactly how
    # the MCP server invokes the CLI — would block until timeout because the
    # long-lived server keeps the pipe's write end open and EOF never comes.
    subprocess.Popen(
        [sys.executable, "-c", runner, str(spec_path)],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.monotonic() + ready_timeout_s
    while time.monotonic() < deadline:
        if url_file.exists():
            return url_file.read_text().strip()
        time.sleep(0.05)
    raise TimeoutError(
        f"detached dashboard server did not publish {url_file} "
        f"within {ready_timeout_s}s"
    )
