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
import socketserver
import threading
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
