"""Command-line interface for agent-readiness (click-based)."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from agent_readiness import __version__
from agent_readiness.checks import _ensure_loaded, all_checks, get_check
from agent_readiness.context import RepoContext
from agent_readiness.renderers import json_renderer, terminal
from agent_readiness.sandbox import SandboxUnavailableError, preflight
from agent_readiness.scorer import score as score_results


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
@click.option("--no-rich", is_flag=True,
              help="Force plain-text output even when rich is available.")
@click.option("--run", "run", is_flag=True,
              help="Execute build/test inside a Docker sandbox. "
                   "Requires Docker. Phase 2 — gated for now.")
def scan(path: Path, json_output: bool, no_rich: bool, run: bool) -> None:
    """Scan a repository and print an AI-readiness report.

    Phase 1: static checks only. `--run` is reserved for Phase 2 and
    currently exits cleanly after a Docker preflight.
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

    _ensure_loaded()
    ctx = RepoContext(root=path)
    results = [spec.fn(ctx) for spec in all_checks()]
    # Apply registry weights to results that didn't override.
    for cr, spec in zip(results, all_checks(), strict=True):
        if cr.weight == 1.0 and spec.weight != 1.0:
            cr.weight = spec.weight
    report = score_results(ctx.root, results)

    if json_output:
        click.echo(json_renderer.render(report))
        return

    use_rich = None
    if no_rich:
        use_rich = False
    click.echo(terminal.render(report, use_rich=use_rich))

    # Headless contract: exit non-zero when overall score is poor enough
    # to be useful as a CI signal. Threshold deliberately conservative;
    # configurable in a later phase.
    sys.exit(0)


@cli.command("list-checks")
def list_checks() -> None:
    """List all registered checks (headless, machine-readable).

    Output is one check per line: `<check_id>\\t<pillar>\\t<title>`.
    Stable, parseable, and zero ceremony.
    """
    _ensure_loaded()
    for spec in all_checks():
        click.echo(f"{spec.check_id}\t{spec.pillar.value}\t{spec.title}")


@cli.command()
@click.argument("check_id")
def explain(check_id: str) -> None:
    """Print the rationale for a check: which agent failure mode it predicts.

    Designed to be readable both by humans and agents grepping for
    fix guidance.
    """
    _ensure_loaded()
    spec = get_check(check_id)
    if spec is None:
        click.echo(f"error: unknown check id: {check_id!r}", err=True)
        click.echo("Run `agent-readiness list-checks` to see available ids.",
                   err=True)
        sys.exit(2)
    click.echo(f"{spec.check_id}")
    click.echo(f"  pillar: {spec.pillar.value}")
    click.echo(f"  title:  {spec.title}")
    click.echo("")
    click.echo(spec.explanation)


if __name__ == "__main__":
    cli()
