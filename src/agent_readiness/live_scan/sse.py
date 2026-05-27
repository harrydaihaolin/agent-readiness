"""SSE handler — streams ``events.jsonl`` to the browser.

Wired into the bundled HTTP server's request dispatcher (see
:mod:`live_scan.server`). Handles one request: a long-lived
``text/event-stream`` response per browser tab.

Replay semantics
================
- If the request carries a ``Last-Event-ID`` header, the handler
  starts the tail at ``int(header) + 1``. Standard SSE auto-reconnect.
- If the request URL has a ``?since=<seq>`` query, that overrides the
  header (useful for clients that haven't read the snapshot yet).
- Without either, the handler returns the entire log + tail.

Terminating
===========
The tail loop ends when a ``scan.exited`` event flows past, or when the
client closes the connection (``BrokenPipeError`` / ``ConnectionResetError``
on write). Server idle-timeout is the existing 600s ``scan-and-view``
behavior — unrelated to SSE streams.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent_readiness.live_scan.events import EventLog


# How long the tail blocks between EOF checks (s). Small enough to feel
# live; large enough that the idle loop is ~0 CPU.
_TAIL_POLL_S = 0.25

# Hard ceiling on time per request so we don't accumulate zombie threads
# if the OS doesn't notify us of a half-closed TCP connection. The
# browser's native EventSource reconnects so this is invisible to UX.
_MAX_STREAM_S = 60 * 30  # 30 min


def handle_sse_request(handler, scan_dir: Path, after_seq: int = -1) -> None:
    """Write the SSE response on ``handler``.

    ``handler`` is the live ``http.server.BaseHTTPRequestHandler``.
    Returns when the stream ends (scan exited, client disconnected,
    or hard ceiling hit) — the caller should not write further.
    """
    # Honor Last-Event-ID header (auto-set by EventSource on reconnect).
    last_id = handler.headers.get("Last-Event-ID")
    if last_id is not None:
        try:
            after_seq = max(after_seq, int(last_id))
        except ValueError:
            pass  # malformed; keep caller-provided after_seq

    log = EventLog(scan_dir)

    # Tell the HTTP server to close the socket when we return — SSE
    # auto-reconnects on the browser side, so there's no benefit to
    # keep-alive and big downside to the connection hanging open after
    # we finish streaming (test clients block forever on resp.read()).
    handler.close_connection = True

    # 204 if the caller is asking for events strictly past what we have.
    if after_seq >= log.next_seq:
        handler.send_response(204)
        handler.send_header("Connection", "close")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("Connection", "close")
    # Disable nginx-style buffering if anyone proxies us; harmless on
    # the direct same-origin localhost path.
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()

    import time
    start = time.monotonic()

    def _hit_ceiling(_ev):
        return (time.monotonic() - start) > _MAX_STREAM_S

    saw_exit = {"flag": False}

    def _stop(ev):
        if _hit_ceiling(ev):
            return True
        if ev is not None and ev.get("event") == "scan.exited":
            # Emit the exit event, then stop on the next poll.
            saw_exit["flag"] = True
            return False
        return saw_exit["flag"]

    try:
        for ev in log.tail(after_seq, poll_interval_s=_TAIL_POLL_S, stop_predicate=_stop):
            _write_sse_event(handler, ev)
    except (BrokenPipeError, ConnectionResetError, OSError):
        # Client went away. Normal — let the request die quietly.
        return


def _write_sse_event(handler, event: dict) -> None:
    """Format one event into SSE wire format and write.

    Wire format (spec):

        id: <seq>
        event: <name>
        data: <single line of JSON>
        \\n
    """
    seq = event.get("seq", 0)
    name = event.get("event", "message")
    payload = json.dumps(event, separators=(",", ":"), default=str)
    out = f"id: {seq}\nevent: {name}\ndata: {payload}\n\n".encode("utf-8")
    handler.wfile.write(out)
    handler.wfile.flush()
