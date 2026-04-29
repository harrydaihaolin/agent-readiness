"""Command-line interface for agent-readiness (click-based)."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from agent_readiness import __version__
from agent_readiness.context import RepoContext
from agent_readiness.renderers import terminal
from agent_readiness.rules_eval import evaluate_rules
from agent_readiness.rules_runtime import get_rule, load_default_rules
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
@click.option("--weights", "weights_file", type=click.STRING,
              default=None,
              help="TOML file path or named preset: strict, lax, default.")
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
@click.option("--no-progress", is_flag=True,
              help="Disable the per-check progress indicator on stderr "
                   "(auto-disabled for --json and non-TTY stderr).")
@click.option("--rules-dir", "rules_dir", type=click.Path(path_type=Path,
                                                          file_okay=False,
                                                          dir_okay=True,
                                                          exists=True),
              default=None,
              help="Override the vendored rules pack with rules from DIR. "
                   "Useful when working on rule changes locally.")
def scan(
    path: Path,
    json_output: bool,
    no_rich: bool,
    run: bool,
    weights_file: str | None,
    only_checks: str | None,
    baseline_file: Path | None,
    fail_below: int,
    report_file: Path | None,
    badge_file: Path | None,
    sarif_file: Path | None,
    no_progress: bool,
    rules_dir: Path | None,
) -> None:
    """Scan a repository and print an AI-readiness report.

    All checks live as YAML rules in the vendored rules pack (or the
    directory passed via ``--rules-dir``). The OSS evaluator dispatches
    to built-in match types and to private matchers registered by
    ``agent_readiness.rules_eval.private_matchers`` at import time.
    """
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
        setup_run = sandbox.run(Phase.SETUP, ["sh", "-c", "echo setup done"])
        if not setup_run.succeeded:
            click.echo(f"Setup phase failed (exit {setup_run.exit_code})", err=True)

        test_run = sandbox.run(Phase.TEST, ["sh", "-c", "echo test done"])
        if not test_run.succeeded:
            click.echo(f"Test phase failed (exit {test_run.exit_code})", err=True)

    from agent_readiness.config import (
        extract_context_config, extract_weights, load_config, resolve_weights,
    )
    repo_config = load_config(path)
    weights = extract_weights(repo_config)

    if weights_file is not None:
        override = resolve_weights(weights_file)
        if override:
            weights = override

    # Plugins may register additional private matchers at import time.
    # They cannot register YAML rules; for that, ship a separate rules
    # directory and pass --rules-dir.
    from agent_readiness.plugins import load_entry_point_plugins, load_local_plugins
    load_local_plugins(path)
    load_entry_point_plugins()

    ctx = RepoContext(root=path, context_config=extract_context_config(repo_config))
    rules = load_default_rules(rules_dir)

    if not rules:
        click.echo(
            "error: no rules loaded. Pass --rules-dir DIR or reinstall "
            "agent-readiness so the vendored rules pack is present.",
            err=True,
        )
        sys.exit(2)

    # Filter by --only if provided. Tokens may be either rule ids or
    # pillar names ("flow", "feedback", "cognitive_load", "safety").
    if only_checks:
        tokens = {t.strip().lower() for t in only_checks.split(",")}
        rules = [
            r for r in rules
            if r.rule_id.lower() in tokens or r.pillar.lower() in tokens
        ]

    from agent_readiness.renderers.progress import ScanProgress
    progress_enabled: bool | None = None
    if no_progress or json_output:
        progress_enabled = False

    results = []
    with ScanProgress(total=len(rules), enabled=progress_enabled) as progress:
        for rule in rules:
            progress.advance(rule.rule_id)
            results.extend(evaluate_rules([rule], ctx))

    report = score_results(ctx.root, results, weights=weights)
    report.languages = ctx.detected_languages
    report.monorepo_tools = ctx.monorepo_tools

    delta_overall: float | None = None
    delta_pillars: dict[str, float] | None = None
    delta_checks: dict[str, float] | None = None
    if baseline_file is not None and baseline_file.is_file():
        import json
        try:
            baseline_data = json.loads(baseline_file.read_text())
            baseline_score = float(baseline_data.get("overall_score", 0))
            delta_overall = round(report.overall_score - baseline_score, 1)
            delta_pillars = {}
            delta_checks = {}
            baseline_checks: dict[str, float] = {}
            for bp in baseline_data.get("pillars", []):
                for bc in bp.get("checks", []):
                    cid = bc.get("check_id")
                    if cid:
                        baseline_checks[cid] = float(bc.get("score", 0))
            for ps in report.pillar_scores:
                for bp in baseline_data.get("pillars", []):
                    if bp.get("pillar") == ps.pillar.value:
                        delta_pillars[ps.pillar.value] = round(
                            ps.score - float(bp.get("score", 0)), 1
                        )
                        break
                for cr in ps.check_results:
                    if cr.check_id in baseline_checks:
                        delta_checks[cr.check_id] = round(
                            cr.score - baseline_checks[cr.check_id], 1
                        )
        except (KeyError, ValueError, json.JSONDecodeError):
            pass

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
            d["delta"] = {
                "overall": delta_overall,
                "pillars": delta_pillars or {},
                "checks": delta_checks or {},
            }
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


@cli.command("scaffold")
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True,
                                        path_type=Path),
                default=Path("."))
@click.option("--dry-run", is_flag=True,
              help="Print what would be created without writing any files.")
@click.option("--force", is_flag=True,
              help="Overwrite files that already exist.")
@click.option("--only", "only_checks", default=None,
              help="Comma-separated check IDs to scaffold for.")
def scaffold(path: Path, dry_run: bool, force: bool, only_checks: str | None) -> None:
    """Generate missing agent-readiness files from templates.

    Scans the repo, identifies checks that are failing due to missing files,
    and writes minimal template files to fix them. Use --dry-run to preview.
    """
    from agent_readiness.scaffold import run_scaffold
    run_scaffold(path, dry_run=dry_run, force=force, only_checks=only_checks)


@cli.command("mcp")
@click.option("--transport", default="stdio",
              type=click.Choice(["stdio"]),
              help="MCP transport (currently only stdio is supported).")
def mcp_serve(transport: str) -> None:
    """Start an MCP server exposing agent-readiness tools to AI agents.

    Requires: pip install agent-readiness[mcp]
    """
    try:
        from agent_readiness.mcp_server import main as mcp_main
    except ImportError:
        click.echo(
            "error: MCP server requires the mcp package. "
            "Install with: pip install agent-readiness[mcp]",
            err=True,
        )
        sys.exit(1)
    mcp_main()


@cli.command("rules-eval")
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True,
                                        exists=True, path_type=Path),
                default=Path("."))
@click.option("--rules", "rules_dir", type=click.Path(path_type=Path,
                                                      file_okay=False,
                                                      dir_okay=True,
                                                      exists=True),
              default=None,
              help="Directory containing rule YAML files; defaults to the "
                   "vendored rules pack.")
@click.option("--json", "json_output", is_flag=True,
              help="Emit findings as JSON (one object per line).")
def rules_eval(path: Path, rules_dir: Path | None, json_output: bool) -> None:
    """Evaluate the YAML rules pack against PATH (diagnostic).

    Equivalent to ``scan`` but skips scoring/rendering and prints raw
    finding lists. Used by ``agent-readiness-rules`` CI to validate
    that new rules fire on expected fixtures.
    """
    ctx = RepoContext(root=path)
    loaded = load_default_rules(rules_dir)
    if not loaded:
        click.echo(
            "error: no rules directory available. "
            "Pass --rules DIR or reinstall agent-readiness with the "
            "vendored rules pack.",
            err=True,
        )
        sys.exit(2)

    results = evaluate_rules(loaded, ctx)

    if json_output:
        import json as _json
        out = {
            "repo_path": str(path.resolve()),
            "rules_evaluated": len(loaded),
            "checks": [r.to_dict() for r in results],
        }
        click.echo(_json.dumps(out, indent=2, sort_keys=False))
        return

    click.echo(f"Evaluated {len(loaded)} rules")
    n_with = sum(1 for r in results if r.findings)
    n_skip = sum(1 for r in results if r.not_measured)
    n_clean = len(results) - n_with - n_skip
    click.echo(f"  passing: {n_clean}, with findings: {n_with}, not measured: {n_skip}")
    for r in results:
        if not r.findings:
            continue
        click.echo("")
        click.echo(f"[{r.pillar.value}] {r.check_id} (score {r.score:.0f})")
        for f in r.findings[:5]:
            loc = f"{f.file}" + (f":{f.line}" if f.line else "")
            click.echo(f"  - {loc}: {f.message}")
        if len(r.findings) > 5:
            click.echo(f"  ... and {len(r.findings) - 5} more")


@cli.command("list-checks")
def list_checks() -> None:
    """List all loaded rules (headless, machine-readable).

    Output is one rule per line: ``<rule_id>\\t<pillar>\\t<title>``.
    Stable, parseable, and zero ceremony.
    """
    rules = load_default_rules()
    for r in rules:
        click.echo(f"{r.rule_id}\t{r.pillar}\t{r.title}")


@cli.command()
@click.argument("check_id")
def explain(check_id: str) -> None:
    """Print the rationale for a check: which agent failure mode it predicts.

    Designed to be readable both by humans and agents grepping for
    fix guidance.
    """
    rule = get_rule(check_id)
    if rule is None:
        click.echo(f"error: unknown check id: {check_id!r}", err=True)
        click.echo("Run `agent-readiness list-checks` to see available ids.",
                   err=True)
        sys.exit(2)
    click.echo(f"{rule.rule_id}")
    click.echo(f"  pillar: {rule.pillar}")
    click.echo(f"  title:  {rule.title}")
    if rule.fix_hint:
        click.echo(f"  fix:    {rule.fix_hint}")
    click.echo("")
    click.echo(rule.explanation or "(no explanation provided)")


if __name__ == "__main__":
    cli()
