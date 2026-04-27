"""Command-line interface for agent-readiness (click-based)."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from agent_readiness import __version__
from agent_readiness.checks import _ensure_loaded, all_checks, get_check
from agent_readiness.context import RepoContext
from agent_readiness.renderers import terminal
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
              help="Execute build/test inside a Docker sandbox. Requires Docker.")
@click.option("--weights", "weights_file", type=click.Path(path_type=Path),
              default=None, help="Path to a TOML file with custom pillar weights.")
@click.option("--only", "only_checks", default=None,
              help="Comma-separated check IDs or pillar names to run.")
@click.option("--baseline", "baseline_file", type=click.Path(path_type=Path),
              default=None, help="Path to a previous JSON report for delta display.")
@click.option("--fail-below", "fail_below", type=int, default=0,
              help="Exit 1 if overall score is below N (0 = disabled).")
@click.option("--report", "report_file", type=click.Path(path_type=Path),
              default=None, help="Write an HTML report to FILE.")
@click.option("--badge", "badge_file", type=click.Path(path_type=Path),
              default=None, help="Write an SVG badge to FILE.")
@click.option("--sarif", "sarif_file", type=click.Path(path_type=Path),
              default=None, help="Write SARIF 2.1.0 output to FILE.")
def scan(
    path: Path,
    json_output: bool,
    no_rich: bool,
    run: bool,
    weights_file: Path | None,
    only_checks: str | None,
    baseline_file: Path | None,
    fail_below: int,
    report_file: Path | None,
    badge_file: Path | None,
    sarif_file: Path | None,
) -> None:
    """Scan a repository and print an AI-readiness report."""
    from agent_readiness.sandbox import (
        DockerSandbox, SandboxConfig,
        detect_docker_native, resolve_image,
    )

    if run:
        try:
            preflight()
        except SandboxUnavailableError as exc:
            click.echo(f"error: {exc.message}", err=True)
            sys.exit(exc.exit_code)

        reason = detect_docker_native(path)
        if reason:
            click.echo(
                f"error: Repo is docker-native ({reason}). "
                "Running inside a nested container is unsafe. "
                "Remove `--run` or use a different repo.",
                err=True,
            )
            sys.exit(2)

        config = SandboxConfig()
        image = resolve_image(path, config)
        sandbox = DockerSandbox(path, config, image)

        click.echo(f"Sandbox image: {image.reference} ({image.source.value})", err=True)
        for note in image.notes:
            click.echo(f"  {note}", err=True)

        from agent_readiness.sandbox import Phase
        # Run setup phase
        setup_run = sandbox.run(Phase.SETUP, ["sh", "-c", "echo setup done"])
        if not setup_run.succeeded:
            click.echo(f"Setup phase failed (exit {setup_run.exit_code})", err=True)

        # Run test phase
        test_run = sandbox.run(Phase.TEST, ["sh", "-c", "echo test done"])
        if not test_run.succeeded:
            click.echo(f"Test phase failed (exit {test_run.exit_code})", err=True)

    # Load config from .agent-readiness.toml
    from agent_readiness.config import extract_weights, load_config
    repo_config = load_config(path)
    weights = extract_weights(repo_config)

    # Override with explicit weights file if provided
    if weights_file is not None:
        import tomllib
        with weights_file.open("rb") as f:
            wf_data = tomllib.load(f)
        override = extract_weights(wf_data)
        if override:
            weights = override

    # Load plugins before ensuring checks
    from agent_readiness.plugins import load_entry_point_plugins, load_local_plugins
    load_local_plugins(path)
    load_entry_point_plugins()

    _ensure_loaded()
    ctx = RepoContext(root=path)
    specs = all_checks()

    # Filter by --only if provided
    if only_checks:
        tokens = {t.strip().lower() for t in only_checks.split(",")}
        filtered = []
        for spec in specs:
            if spec.check_id in tokens:
                filtered.append(spec)
            elif spec.pillar.value.lower() in tokens:
                filtered.append(spec)
        specs = filtered

    results = [spec.fn(ctx) for spec in specs]
    # Apply registry weights to results that didn't override.
    for cr, spec in zip(results, specs, strict=True):
        if cr.weight == 1.0 and spec.weight != 1.0:
            cr.weight = spec.weight

    report = score_results(ctx.root, results, weights=weights)

    # Compute delta if baseline provided
    delta_overall: float | None = None
    delta_pillars: dict[str, float] | None = None
    if baseline_file is not None and baseline_file.is_file():
        import json
        try:
            baseline_data = json.loads(baseline_file.read_text())
            baseline_score = float(baseline_data.get("overall_score", 0))
            delta_overall = round(report.overall_score - baseline_score, 1)
            delta_pillars = {}
            for ps in report.pillar_scores:
                for bp in baseline_data.get("pillars", []):
                    if bp.get("pillar") == ps.pillar.value:
                        delta_pillars[ps.pillar.value] = round(
                            ps.score - float(bp.get("score", 0)), 1
                        )
                        break
        except (KeyError, ValueError, json.JSONDecodeError):
            pass

    # Write optional outputs
    if report_file is not None:
        try:
            from agent_readiness.renderers import html_renderer
            html_content = html_renderer.render(report)
            report_file.write_text(html_content, encoding="utf-8")
        except ImportError as exc:
            click.echo(f"error: {exc}. Install with: pip install agent-readiness[report]",
                       err=True)

    if badge_file is not None:
        svg = _make_badge(report.overall_score)
        badge_file.write_text(svg, encoding="utf-8")

    if sarif_file is not None:
        from agent_readiness.renderers import sarif
        sarif_file.write_text(sarif.render(report), encoding="utf-8")

    if json_output:
        d = report.to_dict()
        if delta_overall is not None:
            d["delta"] = {"overall": delta_overall, "pillars": delta_pillars or {}}
        import json
        click.echo(json.dumps(d, indent=2, sort_keys=False))
    else:
        use_rich = None
        if no_rich:
            use_rich = False
        output = terminal.render(report, use_rich=use_rich)
        if delta_overall is not None:
            sign = "+" if delta_overall >= 0 else ""
            output = output.replace(
                f"{report.overall_score:.1f} / 100",
                f"{report.overall_score:.1f} / 100  ({sign}{delta_overall})",
            )
        click.echo(output)

    # --fail-below gate
    if fail_below > 0 and report.overall_score < fail_below:
        sys.exit(1)

    sys.exit(0)


def _make_badge(score: float) -> str:
    color = (
        "brightgreen" if score >= 80
        else "yellow" if score >= 60
        else "orange" if score >= 40
        else "red"
    )
    label = "AI readiness"
    value = f"{score:.0f}/100"
    lw, rw = len(label) * 6 + 20, len(value) * 6 + 20
    tw = lw + rw
    fill_color = (
        "#4c1" if color == "brightgreen"
        else "#dfb317" if color == "yellow"
        else "#fe7d37" if color == "orange"
        else "#e05d44"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{tw}" height="20">
  <linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
  <stop offset="1" stop-opacity=".1"/></linearGradient>
  <rect rx="3" width="{tw}" height="20" fill="#555"/>
  <rect rx="3" x="{lw}" width="{rw}" height="20" fill="{fill_color}"/>
  <rect x="{lw}" width="4" height="20" fill="{fill_color}"/>
  <rect rx="3" width="{tw}" height="20" fill="url(#s)"/>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="{lw // 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{lw // 2}" y="14">{label}</text>
    <text x="{lw + rw // 2}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{lw + rw // 2}" y="14">{value}</text>
  </g>
</svg>"""


@cli.command()
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True,
                                        path_type=Path),
                default=Path("."))
def init(path: Path) -> None:
    """Write a default .agent-readiness.toml configuration file."""
    config_path = path / ".agent-readiness.toml"
    if config_path.exists():
        click.echo(f"{config_path} already exists. Remove it first to reinitialise.",
                   err=True)
        sys.exit(1)

    config_path.write_text(
        "# agent-readiness configuration\n"
        "# https://github.com/your-org/agent-readiness\n"
        "\n"
        "[weights]\n"
        "# Default weights (must sum to 1.0)\n"
        "# feedback = 0.40\n"
        "# cognitive_load = 0.30\n"
        "# flow = 0.30\n"
        "\n"
        "[ignore]\n"
        "# checks = [\"check.id1\", \"check.id2\"]\n"
        "# paths = [\"vendor/\", \"third_party/\"]\n",
        encoding="utf-8",
    )
    click.echo(f"Wrote {config_path}")


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
