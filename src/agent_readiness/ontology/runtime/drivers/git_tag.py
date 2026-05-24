from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

from agent_readiness.ontology.runtime.drivers.base import (
    DriverResult,
    DriverUnavailableError,
)


class GitTagDriver:
    def execute(
        self, command: str, args: dict[str, Any], *, dry_run: bool = False
    ) -> DriverResult:
        tag_name = str(args.get("tag") or args.get("name") or "")
        remote = str(args.get("remote") or "origin")
        if dry_run:
            run_cmd = command or f"git tag {tag_name} && git push {remote} {tag_name}"
            return DriverResult(
                success=True,
                stdout="(dry-run)",
                stderr="",
                command_run=run_cmd,
                duration_ms=0,
            )
        if shutil.which("git") is None:
            raise DriverUnavailableError("git executable not found on PATH")
        if tag_name and _tag_exists(tag_name):
            return DriverResult(
                success=True,
                stdout=f"tag {tag_name} already exists",
                stderr="",
                command_run=f"git tag {tag_name} (skipped)",
                duration_ms=0,
            )
        run_cmd = command or f"git tag {tag_name} && git push {remote} {tag_name}"
        start = time.monotonic()
        proc = subprocess.run(
            run_cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return DriverResult(
            success=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            command_run=run_cmd,
            duration_ms=duration_ms,
        )


def _tag_exists(tag_name: str) -> bool:
    proc = subprocess.run(
        ["git", "tag", "-l", tag_name],
        capture_output=True,
        text=True,
        check=False,
    )
    return tag_name in proc.stdout.splitlines()
