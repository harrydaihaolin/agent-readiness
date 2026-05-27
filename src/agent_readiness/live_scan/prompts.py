"""Interactive prompt log + state machine — ``<scan_dir>/prompts.jsonl``.

Records (one per line):

  * ``requested`` — prompt was enqueued; carries payload + default + blocking
  * ``answered``  — user submitted an answer (or the scanner did, via default)
  * ``expired``   — scanner applied the per-rule default after ``timeout_s``

Three origins (per spec § 9):

  1. **Pre-scan** — the skill writes ``requested`` lines BEFORE calling
     ``scan_workspace_async``. Worker reads them on startup and:
       * waits up to ``timeout_s`` for ``answered``;
       * applies ``default_action`` on timeout (emits ``expired``);
       * exposes the chosen value to the scan.
  2. **Mid-scan** — rule evaluators call :func:`PromptLog.enqueue` via the
     bus; default is applied immediately (``timeout_s=0``) so the scan
     never stalls. Later answer is recorded as a superseding event.
  3. **Post-scan** — scorer enqueues ``topaction`` + ``ratify`` prompts;
     these never expire (``timeout_s=None``).

Companion to :mod:`live_scan.events` — every state change here ALSO
emits the matching SSE event (``prompt.requested`` / ``prompt.answered``
/ ``prompt.expired``) through the bus, so the dashboard stays in sync
without polling this file directly.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent_readiness_insights_protocol import (
    PromptAnsweredEvent,
    PromptAnswer,
    PromptDefaultAction,
    PromptExpiredEvent,
    PromptPayload,
    PromptRecord,
    PromptRequestedEvent,
)

from agent_readiness.live_scan.events import EventLog


PROMPTS_FILENAME = "prompts.jsonl"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def prompts_path(scan_dir: Path) -> Path:
    return Path(scan_dir) / PROMPTS_FILENAME


def new_prompt_id() -> str:
    """Short opaque id, e.g. ``p-7a3b9c``. Stable for the prompt's
    entire lifetime (request → answer → expire all share one)."""
    return f"p-{uuid.uuid4().hex[:6]}"


class PromptLog:
    """Append-only log of prompt state-machine transitions.

    Backed by ``<scan_dir>/prompts.jsonl``. Each :class:`PromptLog` holds
    a reference to the :class:`EventLog` for the same scan_dir so it
    can fan out matching SSE events on every transition.
    """

    def __init__(self, scan_dir: Path, event_log: EventLog) -> None:
        self.scan_dir = Path(scan_dir)
        self.scan_dir.mkdir(parents=True, exist_ok=True)
        self._path = prompts_path(self.scan_dir)
        self._events = event_log
        self._lock = threading.Lock()
        # In-memory index of every prompt seen, keyed by prompt_id, for
        # fast state queries (pending, answered, expired). Rebuilt on
        # construct from the on-disk log so a re-attaching server stays
        # consistent across restarts.
        self._state: dict[str, dict] = {}
        self._reindex()

    # ------------------------------------------------------------------
    # persistence helpers
    # ------------------------------------------------------------------

    def _write_record(self, record: PromptRecord) -> None:
        line = record.model_dump_json(exclude_none=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")
            f.flush()

    def _reindex(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    return  # torn tail
                pid = obj.get("prompt_id")
                if not pid:
                    continue
                event = obj.get("event")
                slot = self._state.setdefault(pid, {})
                if event == "requested":
                    slot["payload"] = obj.get("payload")
                    slot["default_action"] = obj.get("default_action")
                    slot["blocking"] = obj.get("blocking", False)
                    slot["timeout_s"] = obj.get("timeout_s")
                    slot["status"] = slot.get("status", "pending")
                elif event == "answered":
                    slot["answer"] = obj.get("answer")
                    slot["source"] = obj.get("source")
                    if slot.get("status") == "default_applied":
                        slot["status"] = "superseded"
                    else:
                        slot["status"] = "answered"
                elif event == "expired":
                    if slot.get("status") in (None, "pending"):
                        slot["status"] = "default_applied"

    # ------------------------------------------------------------------
    # transitions — each emits both a JSONL line and an SSE event
    # ------------------------------------------------------------------

    def enqueue(
        self,
        *,
        prompt_id: Optional[str] = None,
        payload: PromptPayload,
        default_action: PromptDefaultAction,
        blocking: bool = False,
        timeout_s: Optional[int] = None,
    ) -> str:
        """Record a new ``requested`` event. Returns the prompt_id.

        If ``timeout_s`` is None and ``blocking`` is False, the prompt
        sits open until answered (used for post-scan top-action /
        ratify prompts).
        """
        with self._lock:
            pid = prompt_id or new_prompt_id()
            at = datetime.now(timezone.utc)
            rec = PromptRecord(
                seq=0,  # not the SSE seq — kept here as the line number
                event="requested",
                prompt_id=pid,
                at=at,
                payload=payload,
                default_action=default_action,
                blocking=blocking,
                timeout_s=timeout_s,
            )
            self._write_record(rec)
            self._state[pid] = {
                "payload": payload.model_dump(mode="json"),
                "default_action": default_action.model_dump(mode="json"),
                "blocking": blocking,
                "timeout_s": timeout_s,
                "status": "pending",
            }

            ev = PromptRequestedEvent(
                seq=self._events.next_seq,
                at=at,
                prompt_id=pid,
                blocking=blocking,
                payload=payload,
                default_action=default_action,
            )
            self._events.emit(ev)
            return pid

    def answer(
        self,
        prompt_id: str,
        *,
        answer: PromptAnswer,
        source: str = "browser",
    ) -> None:
        """Record an ``answered`` event. ``source`` is ``browser`` or
        ``default``. Idempotent on identical body — duplicate calls
        re-emit the SSE event but don't corrupt state.
        """
        if source not in ("browser", "default"):
            raise ValueError(f"source must be 'browser' or 'default'; got {source!r}")
        with self._lock:
            if prompt_id not in self._state:
                raise KeyError(f"unknown prompt_id {prompt_id!r}")
            at = datetime.now(timezone.utc)
            rec = PromptRecord(
                seq=0,
                event="answered",
                prompt_id=prompt_id,
                at=at,
                answer=answer,
                source=source,  # type: ignore[arg-type]
            )
            self._write_record(rec)
            prev = self._state[prompt_id]
            if prev.get("status") == "default_applied":
                prev["status"] = "superseded"
            else:
                prev["status"] = "answered"
            prev["answer"] = answer.model_dump(mode="json")
            prev["source"] = source

            ev = PromptAnsweredEvent(
                seq=self._events.next_seq,
                at=at,
                prompt_id=prompt_id,
                answer=answer,
                source=source,  # type: ignore[arg-type]
            )
            self._events.emit(ev)

    def expire(self, prompt_id: str) -> None:
        """Record an ``expired`` event using the prompt's stored
        ``default_action``. Idempotent — calling on an already-expired
        prompt is a no-op."""
        with self._lock:
            slot = self._state.get(prompt_id)
            if slot is None:
                raise KeyError(f"unknown prompt_id {prompt_id!r}")
            if slot.get("status") in ("default_applied", "answered", "superseded"):
                return
            at = datetime.now(timezone.utc)
            default = slot.get("default_action")
            if default is None:
                raise RuntimeError(
                    f"prompt {prompt_id!r} has no default_action; cannot expire"
                )
            # Re-hydrate the typed default for the SSE event.
            from pydantic import TypeAdapter
            adapter = TypeAdapter(PromptDefaultAction)
            default_typed = adapter.validate_python(default)
            rec = PromptRecord(
                seq=0,
                event="expired",
                prompt_id=prompt_id,
                at=at,
                default_action=default_typed,
            )
            self._write_record(rec)
            slot["status"] = "default_applied"
            slot["effective_answer"] = default

            ev = PromptExpiredEvent(
                seq=self._events.next_seq,
                at=at,
                prompt_id=prompt_id,
                default_action=default_typed,
            )
            self._events.emit(ev)

    # ------------------------------------------------------------------
    # blocking + non-blocking await helpers
    # ------------------------------------------------------------------

    def wait_for_answer(
        self,
        prompt_id: str,
        *,
        timeout_s: Optional[float],
        poll_interval_s: float = 0.1,
    ) -> dict:
        """Block until the prompt is answered, or apply the default on
        timeout. Returns the effective answer dict (browser-supplied if
        answered before timeout, otherwise ``default_action``).

        Used by the worker for pre-scan blocking prompts. Non-blocking
        prompts use :func:`apply_default_immediately` instead.
        """
        deadline = time.monotonic() + timeout_s if timeout_s is not None else None
        while True:
            slot = self._state.get(prompt_id)
            if slot is None:
                raise KeyError(f"unknown prompt_id {prompt_id!r}")
            status = slot.get("status")
            if status == "answered":
                return slot["answer"]
            if status == "default_applied":
                return slot.get("effective_answer", slot["default_action"])
            if deadline is not None and time.monotonic() >= deadline:
                self.expire(prompt_id)
                # Re-read after expire so the answer dict is consistent.
                slot = self._state[prompt_id]
                return slot.get("effective_answer", slot["default_action"])
            time.sleep(poll_interval_s)

    def apply_default_immediately(self, prompt_id: str) -> dict:
        """Synchronously expire a non-blocking prompt and return the
        effective answer. The user can still supersede later — that
        applies to FUTURE evaluators only (see spec § 9.1)."""
        self.expire(prompt_id)
        slot = self._state[prompt_id]
        return slot.get("effective_answer", slot["default_action"])

    # ------------------------------------------------------------------
    # state queries
    # ------------------------------------------------------------------

    def status(self, prompt_id: str) -> str:
        slot = self._state.get(prompt_id)
        if slot is None:
            raise KeyError(prompt_id)
        return slot.get("status", "pending")

    def is_answered(self, prompt_id: str) -> bool:
        return self.status(prompt_id) in ("answered", "superseded")

    def pending_count(self) -> int:
        return sum(1 for s in self._state.values() if s.get("status") == "pending")

    def default_used_for(self) -> list[str]:
        return [
            pid for pid, s in self._state.items()
            if s.get("status") in ("default_applied", "superseded")
        ]

    def list_pending(self) -> list[dict]:
        out: list[dict] = []
        for pid, slot in self._state.items():
            if slot.get("status") == "pending":
                out.append({
                    "prompt_id": pid,
                    "payload": slot.get("payload"),
                    "default_action": slot.get("default_action"),
                    "blocking": slot.get("blocking", False),
                    "timeout_s": slot.get("timeout_s"),
                })
        return out

    def is_known(self, prompt_id: str) -> bool:
        return prompt_id in self._state
