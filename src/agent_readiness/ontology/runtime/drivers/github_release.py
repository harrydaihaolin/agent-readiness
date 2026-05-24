from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any

from agent_readiness.ontology.runtime.drivers.base import (
    DriverAuthError,
    DriverResult,
    DriverUnavailableError,
)


class GitHubReleaseDriver:
    TOKEN_ENV = "GITHUB_TOKEN"

    def execute(
        self, command: str, args: dict[str, Any], *, dry_run: bool = False
    ) -> DriverResult:
        if dry_run:
            return DriverResult(
                success=True,
                stdout="(dry-run)",
                stderr="",
                command_run=command,
                duration_ms=0,
            )
        if not os.environ.get(self.TOKEN_ENV):
            raise DriverAuthError(self.TOKEN_ENV)
        if shutil.which("gh") is None:
            raise DriverUnavailableError("gh executable not found on PATH")
        tag = str(args.get("tag") or args.get("name") or "")
        title = str(args.get("title") or tag)
        run_cmd = command or f"gh release create {tag} --title {title!r}"
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
