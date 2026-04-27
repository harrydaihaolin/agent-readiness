"""Command-line interface for agent-readiness (click-based)."""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path

import click

from agent_readiness import __version__
from agent_readiness.context import RepoContext
from agent_readiness.sandbox import SandboxUnavailableError, preflight


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Benchmark how AI-ready a code repository is for coding agents.",
)
@click.version_option(__version__, prog_name="agent-readiness")
def cli() -> None:
    """agent-readiness CLI."""


@cli.command()
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True,
                                        exists=True, path_type=Path),
                default=Path("."))
@click.option("--json", "json_output", is_flag=True,
              help="Emit a stable JSON report (no rich formatting).")
@click.option("--run", "run", is_flag=True,
              help="Execute build/test inside a Docker sandbox. "
                   "Requires Docker. Phase 2 — gated for now.")
def scan(path: Path, json_output: bool, run: bool) -> None:
    """Scan a repository and print an AI-readiness report.

    Phase 1: static checks only. `--run` is reserved for Phase 2 and
    currently exits with a clear message after preflight.
    """
    if run:
        try:
            preflight()
        except SandboxUnavailableError as exc:
            click.echo(f"error: {exc.message}", err=True)
            sys.exit(exc.exit_code)
        click.echo(
            "Docker is available, but `--run` is gated to Phase 2. "
            "Re-run without `--run` for the static report.",
            err=True,
        )
        sys.exit(2)

    # Phase 1 plumbing: load checks, build context, score, render.
    # The actual check execution lands in the next commit; this branch
    # just builds context and prints a placeholder so the migration is
    # observable in isolation.
    ctx = RepoContext(root=path)
    if json_output:
        payload = {
            "schema": 1,
            "repo_path": str(ctx.root),
            "file_count": len(ctx.files),
            "is_git_repo": ctx.is_git_repo,
            "commit_count": ctx.commit_count,
            "run_mode": "static",
            "phase": 1,
            "note": "checks not yet wired in this commit",
        }
        click.echo(_json.dumps(payload, indent=2))
        return

    click.echo(f"agent-readiness scan: {ctx.root}")
    click.echo(f"  files: {len(ctx.files)}  "
               f"git: {'yes' if ctx.is_git_repo else 'no'}  "
               f"commits: {ctx.commit_count}")
    click.echo("  (no checks registered yet — wiring lands in next commit)")


if __name__ == "__main__":
    cli()
