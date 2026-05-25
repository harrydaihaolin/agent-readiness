"""Local HTTP server: serves packaged dashboard + scan data dir."""
from __future__ import annotations

import http.server
import socketserver
import threading
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path


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


def _make_handler(dist_dir: Path, data_dir: Path):
    """Build a request handler closed over the dist + data directories.

    Special routing:
        ``/data/scan.json`` → ``live.json`` (if exists) else ``latest.json``.
        ``/data/<other>``   → ``<data_dir>/<other>``.
        ``/<other>``        → ``<dist_dir>/<other>``.

    The ``/data/scan.json`` fallback is what the dashboard polls — the spec
    keeps ``live.json`` and ``latest.json`` as separate on-disk files (one
    is renamed to ``archive/`` on completion); the server hides that swap
    from the dashboard.
    """
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(dist_dir), **kwargs)

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
                return str(data_dir / rel) if rel else str(data_dir)
            return super().translate_path(path)

        def log_message(self, format, *args):  # noqa: A002
            return
    return Handler


def start_server(*, host: str, port: int, data_dir: Path) -> LiveServer:
    """Start a ThreadingHTTPServer on a daemon thread. Returns immediately."""
    dist = dashboard_dist_path()
    handler = _make_handler(dist, Path(data_dir))
    httpd = http.server.ThreadingHTTPServer((host, port), handler)
    bound_host, bound_port = httpd.server_address[:2]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return LiveServer(host=bound_host, port=bound_port, _httpd=httpd, _thread=t)
