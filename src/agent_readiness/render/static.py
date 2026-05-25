"""Render a self-contained directory of dashboard + scan JSON.

The output is a portable artifact: ``index.html`` with the scan envelope
inlined as ``window.__SCAN_ENVELOPE__``, plus ``data/scan.json`` (so the
SPA's fetch path still works under ``python -m http.server``), plus the
dashboard ``assets/``. Opens under ``file://`` without CORS surprises.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent_readiness.live_scan.paths import scan_dir, workspace_hash
from agent_readiness.live_scan.server import dashboard_dist_path


@dataclass
class RenderResult:
    index_path: Path
    output_dir: Path
    scan_id: str
    scan_ts: str | None
    rendered_at: str
    source_status: str


def _resolve_envelope(scan_dir_path: Path, scan_id: str | None) -> tuple[Path, str | None]:
    """Pick the envelope file. Returns ``(path, ts-or-None)``."""
    if scan_id is None:
        live = scan_dir_path / "live.json"
        if live.exists():
            return live, None
        latest = scan_dir_path / "latest.json"
        if latest.exists():
            return latest, None
        raise FileNotFoundError(f"no scan history in {scan_dir_path}")
    if scan_id == "latest":
        latest = scan_dir_path / "latest.json"
        if not latest.exists():
            raise FileNotFoundError(f"no latest.json in {scan_dir_path}")
        return latest, None
    archived = scan_dir_path / "archive" / f"{scan_id}.json"
    if not archived.exists():
        raise FileNotFoundError(f"no archived scan {scan_id} in {scan_dir_path}")
    return archived, scan_id


def _inline_envelope(html: str, envelope: dict) -> str:
    """Inject ``window.__SCAN_ENVELOPE__`` into the index.html."""
    snippet = (
        f"<script>window.__SCAN_ENVELOPE__ = {json.dumps(envelope)};</script>"
    )
    if "</head>" in html:
        return html.replace("</head>", f"{snippet}</head>", 1)
    if "<body>" in html:
        return html.replace("<body>", f"<body>{snippet}", 1)
    return snippet + html


def export_report(
    workspace_path: Path,
    *,
    scan_id: str | None = None,
    output_dir: Path | None = None,
) -> RenderResult:
    """Render a scan as a portable static directory."""
    workspace_path = Path(workspace_path).expanduser().resolve()
    sd = scan_dir(workspace_path)
    if not sd.exists():
        raise FileNotFoundError(f"no scan history for {workspace_path}")
    env_path, ts = _resolve_envelope(sd, scan_id)
    envelope = json.loads(env_path.read_text())
    if output_dir is None:
        wh = workspace_hash(workspace_path)
        output_dir = Path.home() / ".agent-readiness" / "reports" / wh / (ts or "latest")
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    dist = dashboard_dist_path()
    for src in dist.rglob("*"):
        rel = src.relative_to(dist)
        dst = output_dir / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    (output_dir / "data").mkdir(exist_ok=True)
    (output_dir / "data" / "scan.json").write_text(json.dumps(envelope))
    index_html = output_dir / "index.html"
    if index_html.exists():
        html = index_html.read_text()
        html = _inline_envelope(html, envelope)
        index_html.write_text(html)
    return RenderResult(
        index_path=index_html,
        output_dir=output_dir,
        scan_id=workspace_hash(workspace_path),
        scan_ts=ts,
        rendered_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_status=envelope.get("status", "unknown"),
    )
