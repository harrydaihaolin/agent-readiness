"""Minimalistic per-check progress visualizer for `scan`.

Design constraints (matter for the headless-first contract):

- Writes to **stderr only**. Stdout stays clean for piping the report,
  JSON, or snapshot tests.
- **Auto-disables** when stderr is not a TTY (CI, pipes, file redirects)
  or when explicitly disabled (e.g. `--json`, `--no-progress`).
- Uses `rich.progress.Progress` when `rich` is installed (project already
  depends on it); falls back to a single-line `\\r`-overwrite renderer
  when rich is unavailable so the tool still works in stripped envs.
- Leaves **no visual residue** on completion: rich is `transient=True`,
  the plain renderer clears its line on exit. The terminal report is
  the only artefact the user keeps on screen.

Public surface is just `ScanProgress`, used as a context manager:

    with ScanProgress(total=len(specs), enabled=show) as progress:
        for spec in specs:
            progress.advance(spec.check_id)
            results.append(spec.fn(ctx))
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import TracebackType


def _stderr_is_tty() -> bool:
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def _rich_available() -> bool:
    try:
        import rich  # noqa: F401
        import rich.progress  # noqa: F401
        return True
    except ImportError:
        return False


class ScanProgress:
    """Per-check progress indicator on stderr.

    Parameters
    ----------
    total:
        Number of checks expected. Used for the `[N/M]` counter.
    enabled:
        Tri-state. ``None`` = auto (enabled iff stderr is a TTY). ``True``
        forces it on (still respects TTY for the rich variant — falls back
        to plain otherwise). ``False`` makes the whole object a no-op.
    """

    def __init__(self, total: int, *, enabled: bool | None = None) -> None:
        self.total = max(total, 0)
        if enabled is False:
            self._mode = "off"
        elif not _stderr_is_tty():
            self._mode = "off"
        elif _rich_available():
            self._mode = "rich"
        else:
            self._mode = "plain"

        self._completed = 0
        self._rich_progress: Any = None
        self._rich_task_id: Any = None
        self._plain_last_len = 0

    @property
    def enabled(self) -> bool:
        return self._mode != "off"

    def __enter__(self) -> ScanProgress:
        if self._mode == "rich":
            from rich.console import Console
            from rich.progress import (
                BarColumn, MofNCompleteColumn, Progress,
                SpinnerColumn, TextColumn,
            )

            console = Console(file=sys.stderr, stderr=True)
            self._rich_progress = Progress(
                SpinnerColumn(style="cyan"),
                TextColumn("[bold]scanning[/bold]"),
                BarColumn(bar_width=24),
                MofNCompleteColumn(),
                TextColumn("[dim]{task.fields[check_id]}[/dim]"),
                console=console,
                transient=True,
            )
            self._rich_progress.start()
            self._rich_task_id = self._rich_progress.add_task(
                "scan", total=self.total, check_id="…",
            )
        return self

    def advance(self, check_id: str) -> None:
        """Mark *check_id* as the next one being run.

        Call this **before** invoking the check's function so the user
        sees what's currently in flight rather than what just finished.
        """
        if self._mode == "off":
            return

        self._completed += 1

        if self._mode == "rich":
            assert self._rich_progress is not None
            self._rich_progress.update(
                self._rich_task_id,
                advance=1,
                check_id=check_id,
            )
        else:
            line = f"  scanning [{self._completed}/{self.total}] {check_id}"
            pad = max(self._plain_last_len - len(line), 0)
            sys.stderr.write("\r" + line + " " * pad)
            sys.stderr.flush()
            self._plain_last_len = len(line)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._mode == "rich" and self._rich_progress is not None:
            self._rich_progress.stop()
            self._rich_progress = None
        elif self._mode == "plain" and self._plain_last_len:
            sys.stderr.write("\r" + " " * self._plain_last_len + "\r")
            sys.stderr.flush()
            self._plain_last_len = 0
