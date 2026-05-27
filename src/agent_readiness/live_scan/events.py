"""SSE event log — write + read + tail of ``<scan_dir>/events.jsonl``.

This module is the single chokepoint for the new SSE transport added in
Bundle D. Worker code calls :func:`EventLog.append` to record state
changes; the SSE handler in :mod:`live_scan.sse` calls
:func:`EventLog.tail` to stream them out to the browser.

Design
======
- **One-file persistence.** Events live in append-only
  ``<scan_dir>/events.jsonl``. Each line is exactly one
  :class:`agent_readiness_insights_protocol.SSEEvent` dump.
- **Monotonic ``seq``.** Per scan_id, lines are numbered 0, 1, 2, …
  This is both the SSE ``id:`` header (so the browser can replay via
  ``Last-Event-ID``) and the line offset (so a future seek index is
  trivial — though v1 just scans the file).
- **Single writer.** The worker is the only writer per scan. The
  ``threading.Lock`` here is for the rare case where the SSE handler
  responds to an inbound POST by appending an answer event from a
  request thread — but the contract is "writes are serialized." There
  is no cross-process locking; only run one ``scan-and-view`` per
  scan_id at a time (enforced by the existing pidfile).
- **Throttling.** ``maybe_append`` is a convenience for events the
  spec marks as throttled (``repo.evaluator.tick``,
  ``workspace.score.tick``, ``log.line``). It silently drops events
  that arrive within ``min_interval_s`` of the previous emission of
  the same ``(event_type, repo_id)`` key.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from agent_readiness_insights_protocol import SSEEvent


EVENTS_FILENAME = "events.jsonl"

# Default throttle for the three event kinds the spec marks throttled.
_DEFAULT_THROTTLE_S = 0.2  # 5 events/sec per key, matches spec § 6


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def events_path(scan_dir: Path) -> Path:
    return Path(scan_dir) / EVENTS_FILENAME


class EventLog:
    """Append + tail of ``events.jsonl``.

    Each :class:`EventLog` instance owns one scan_dir. Multiple
    instances pointed at the same scan_dir are NOT safe to write from
    concurrently — there must be exactly one writer (the worker).
    Readers can be unlimited; they just open the file fresh each tail.
    """

    def __init__(self, scan_dir: Path) -> None:
        self.scan_dir = Path(scan_dir)
        self.scan_dir.mkdir(parents=True, exist_ok=True)
        self._path = events_path(self.scan_dir)
        self._lock = threading.Lock()
        self._next_seq = self._compute_next_seq()
        # ``(event_type, repo_id_or_None) -> monotonic timestamp`` for
        # the throttle path. Only populated for keys we've actually
        # throttled — never grows beyond the worker's event vocabulary.
        self._last_emit: dict[tuple[str, Optional[str]], float] = {}

    # ------------------------------------------------------------------
    # state inspection
    # ------------------------------------------------------------------

    @property
    def next_seq(self) -> int:
        return self._next_seq

    def _compute_next_seq(self) -> int:
        """On open, scan the existing file to recover ``next_seq``.

        Crash-safe: the last line of a partially-flushed events.jsonl
        is silently skipped if it doesn't parse as JSON, and ``next_seq``
        becomes ``last_valid_seq + 1``. The worker will overwrite the
        torn line on its next append (write is sequential so this is
        safe).
        """
        if not self._path.exists():
            return 0
        last_seq = -1
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    seq = obj.get("seq")
                    if isinstance(seq, int) and seq > last_seq:
                        last_seq = seq
                except json.JSONDecodeError:
                    # Torn write at tail; the next append will overwrite.
                    break
        return last_seq + 1

    # ------------------------------------------------------------------
    # append
    # ------------------------------------------------------------------

    def append(self, event_dict: dict) -> int:
        """Append a fully-formed event dict (no validation here).

        Returns the assigned ``seq``. The caller is expected to have
        produced a dict that round-trips through ``SSEEvent`` — see
        :func:`emit` for the validated variant.
        """
        with self._lock:
            seq = self._next_seq
            event_dict = dict(event_dict)
            event_dict.setdefault("seq", seq)
            event_dict.setdefault("at", _iso_now())
            # If the caller passed a stale seq, respect ours.
            event_dict["seq"] = seq
            line = json.dumps(event_dict, default=str)
            # Use 'a' so multiple opens are fine, and trust the OS write
            # syscall's atomicity for sub-page lines (events are << 4 KiB).
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.write("\n")
                f.flush()
            self._next_seq = seq + 1
            return seq

    def emit(self, event_obj) -> int:
        """Validated wrapper around :func:`append`.

        Accepts any :class:`SSEEvent` leaf (or a dict matching one);
        the discriminated union validates the shape and assigns the
        ``seq`` consistently.
        """
        # If the caller passed a Pydantic instance, dump it; else assume
        # a dict and run through TypeAdapter to validate.
        if hasattr(event_obj, "model_dump"):
            ev_dict = event_obj.model_dump(mode="json")
        else:
            from pydantic import TypeAdapter
            adapter = TypeAdapter(SSEEvent)
            validated = adapter.validate_python(event_obj)
            ev_dict = validated.model_dump(mode="json")
        return self.append(ev_dict)

    def maybe_emit(
        self,
        event_obj,
        *,
        throttle_key: tuple[str, Optional[str]],
        min_interval_s: float = _DEFAULT_THROTTLE_S,
    ) -> Optional[int]:
        """Emit unless the previous same-key emission was within
        ``min_interval_s``. Returns the assigned seq, or None if dropped.
        """
        now = time.monotonic()
        prev = self._last_emit.get(throttle_key)
        if prev is not None and (now - prev) < min_interval_s:
            return None
        self._last_emit[throttle_key] = now
        return self.emit(event_obj)

    # ------------------------------------------------------------------
    # read + tail
    # ------------------------------------------------------------------

    def read_after_seq(self, after_seq: int) -> Iterator[dict]:
        """Yield event dicts with ``seq > after_seq`` from the on-disk
        log. Returns an empty iterator if the file doesn't exist.

        Used by the SSE handler to catch up a reconnecting client to
        ``last_seq``, and by the snapshot builder to materialize state.
        """
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    # Torn line at tail — stop; reader will retry.
                    return
                if isinstance(obj.get("seq"), int) and obj["seq"] > after_seq:
                    yield obj

    def read_all(self) -> Iterator[dict]:
        return self.read_after_seq(-1)

    def tail(
        self,
        after_seq: int,
        *,
        poll_interval_s: float = 0.25,
        stop_predicate=None,
    ) -> Iterator[dict]:
        """Generator that yields events with ``seq > after_seq``,
        blocking between EOF polls.

        Used by the SSE handler. The caller breaks out by closing the
        connection (the generator dies with the request thread) or by
        passing a ``stop_predicate`` that returns True when the tail
        should stop (e.g. when a ``scan.exited`` event has been
        consumed).

        ``poll_interval_s`` is the sleep between EOF polls — chosen
        small enough to feel live (250 ms) and large enough to keep
        CPU near zero. The OS' file system caches the inode, so this
        loop costs ~one syscall per poll.
        """
        seen = after_seq
        while True:
            for obj in self.read_after_seq(seen):
                seen = obj["seq"]
                yield obj
                if stop_predicate is not None and stop_predicate(obj):
                    return
            if stop_predicate is not None and stop_predicate(None):
                return
            time.sleep(poll_interval_s)


# ---------------------------------------------------------------------------
# Module-level helpers (no instance needed for snapshot)
# ---------------------------------------------------------------------------


def iter_events(scan_dir: Path) -> Iterable[dict]:
    """Yield every event dict from ``<scan_dir>/events.jsonl`` in order.

    Convenience for snapshot builders / tests / debug tooling — avoids
    standing up an :class:`EventLog` instance when you only need read.
    """
    p = events_path(Path(scan_dir))
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                return
