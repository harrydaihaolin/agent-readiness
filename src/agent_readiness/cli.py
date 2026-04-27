"""Command-line interface for agent-readiness."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from agent_readiness import __version__
from agent_readiness.context import RepoContext
from agent_readiness.sandbox import SandboxUnavailableError, preflight

app = typer.Typer(
    name="agent-readiness",
    help="Benchmark how agent-ready a code repository is for LLM coding agents.",
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"agent-readiness {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True,
                     help="Show version and exit."),
    ] = False,
) -> None:
    """agent-readiness CLI."""


@app.command()
def scan(
    path: Annotated[Path, typer.Argument(help="Repo to scan.")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
    run: Annotated[
        bool,
        typer.Option(
            "--run",
            help="Execute build/test inside a Docker sandbox. Requires Docker.",
        ),
    ] = False,
) -> None:
    """Scan a repository and print an agent-readiness report.

    By default, runs static checks only (no code from the target repo is
    executed). Pass `--run` to additionally execute build/test commands
    inside a Docker sandbox; this requires a working Docker daemon.
    See SANDBOX.md for the execution model.
    """
    if run:
        try:
            preflight()
        except SandboxUnavailableError as exc:
            console.print(f"[bold red]error:[/bold red] {exc.message}")
            raise typer.Exit(code=exc.exit_code) from exc

    ctx = RepoContext(root=path)
    if json_output:
        import json
        payload = {
            "repo_path": str(ctx.root),
            "file_count": len(ctx.files),
            "is_git_repo": ctx.is_git_repo,
            "commit_count": ctx.commit_count,
            "run_mode": "full" if run else "static",
        }
        console.print_json(json.dumps(payload))
        return

    console.rule("[bold]agent-readiness scan")
    console.print(f"[dim]Repo:[/dim] {ctx.root}")
    console.print(f"[dim]Files:[/dim] {len(ctx.files)}  "
                  f"[dim]Git:[/dim] {'yes' if ctx.is_git_repo else 'no'}  "
                  f"[dim]Commits:[/dim] {ctx.commit_count}  "
                  f"[dim]Mode:[/dim] {'full (Docker)' if run else 'static'}")
    console.print("[yellow]No checks registered yet — v0.1 in progress.[/yellow]")


if __name__ == "__main__":
    app()
