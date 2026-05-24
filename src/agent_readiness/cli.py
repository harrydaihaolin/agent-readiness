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
              help=(
                  "Exit 1 if overall score is below N (0 = disabled). "
                  "Use this in CI to gate merges on the readiness score; "
                  "see ML7 in the leaderboard scan envelope for the same "
                  "convention applied to fleet scans."
              ))
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
@click.option("--apply-top-action", "apply_top_action_flag", is_flag=True,
              help=(
                  "After scanning, apply the single highest-priority "
                  "structured fix (the report's `top_action`) to the "
                  "repo in place. Skips cleanly when no top_action has "
                  "a structured `action` (e.g. v1 rules with only "
                  "fix_hint). Exits 1 if the apply itself fails."
              ))
@click.option("--verify", "verify_flag", is_flag=True,
              help=(
                  "Only meaningful with --apply-top-action. When set, "
                  "run the action's verify command after applying and "
                  "exit 1 if verify fails. No-op without "
                  "--apply-top-action."
              ))
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
    apply_top_action_flag: bool,
    verify_flag: bool,
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
    from agent_readiness.workspace_detect import detect as _detect_workspace

    # Fail loudly when the user hands us a multi-repo workspace. Scoring
    # a parent dir produces silently-garbage numbers today; the structured
    # error names `agent-readiness detect` so the user can recover.
    try:
        _ws = _detect_workspace(path)
    except (OSError, NotADirectoryError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)
    if _ws.classification == "multi_repo_workspace":
        err = {
            "error": "multi_repo_workspace",
            "hint": (
                "this path contains multiple repos; run "
                "`agent-readiness detect <path>` to list them, then scan "
                "each repo individually"
            ),
            "detected_repos": [r.name for r in _ws.repos],
            "root": _ws.root,
            "version": _ws.version,
        }
        import json as _json
        click.echo(_json.dumps(err, indent=2), err=True)
        sys.exit(2)

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

    if apply_top_action_flag:
        from agent_readiness.apply_action import apply_top_action as _apply

        apply_result = _apply(
            report.top_action,
            path,
            run_verify=verify_flag,
        )
        result_dict = apply_result.to_dict()
        if json_output:
            import json as _json
            click.echo(
                _json.dumps({"apply_top_action": result_dict}, indent=2)
            )
        else:
            click.echo("")
            if apply_result.applied:
                written = ", ".join(apply_result.written) or "(no file paths)"
                click.echo(f"Applied top action; wrote: {written}")
                if verify_flag and apply_result.verify is not None:
                    if apply_result.verified:
                        click.echo("Verify command: PASSED")
                    else:
                        click.echo(
                            f"Verify command: FAILED "
                            f"(exit {apply_result.verify.get('exit_code')})"
                        )
            elif apply_result.error:
                click.echo(f"Apply failed: {apply_result.error}", err=True)
            else:
                click.echo(
                    f"Apply skipped: {apply_result.skipped_reason}",
                    err=True,
                )

        if apply_result.error is not None:
            sys.exit(1)
        if verify_flag and apply_result.verified is False:
            sys.exit(1)

    # Exit-code contract (consumed by CI in this repo's
    # `.github/workflows/ci.yml`, by `agent-readiness-leaderboard/scripts/
    # scan.py`, and by downstream tooling that calls the CLI):
    #
    #   0 = scan completed and (if --fail-below was set) the overall
    #       score met or exceeded the threshold.
    #   1 = scan completed but the overall score fell below
    #       --fail-below; treat as a gate failure, not a runtime error.
    #
    # Non-zero exits from earlier in the pipeline (e.g. unhandled
    # exceptions, click usage errors) are *not* part of this contract;
    # callers that want to distinguish "score regressed" from "scanner
    # crashed" should also check stderr or run with --json and look at
    # the envelope. (ML7)
    if fail_below > 0 and report.overall_score < fail_below:
        sys.exit(1)

    sys.exit(0)


@cli.command()
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True,
                                        exists=True, path_type=Path),
                default=Path("."))
@click.option("--json", "json_output", is_flag=True,
              help="Emit the structured detect envelope. Required for "
                   "headless / piped use.")
@click.option("--quiet", "quiet", is_flag=True,
              help="Suppress the human-readable summary. With --json, "
                   "guarantees the only stdout output is the envelope.")
def detect(path: Path, json_output: bool, quiet: bool) -> None:
    """Classify PATH as single repo, monorepo, or multi-repo workspace.

    Prints a human-readable summary by default; use ``--json`` for the
    structured ``detect_v1`` envelope (the same shape the MCP server's
    ``detect_workspace`` tool returns). The CLI never asks the user to
    pick repos — that's the MCP/skill's job. Headless callers should
    pipe ``detect --json`` through ``jq`` and run ``scan`` per repo.

    Exit codes:

    \b
      0  classification resolved (any of the three labels).
      2  path is not a directory, or another input error.
    """
    from agent_readiness.workspace_detect import detect as _detect

    try:
        result = _detect(path)
    except (OSError, NotADirectoryError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)

    if json_output:
        import json as _json
        click.echo(_json.dumps(result.to_dict(), indent=2, sort_keys=False))
        sys.exit(0)

    if quiet:
        sys.exit(0)

    label = {
        "single_repo": "Single repo",
        "monorepo": "Monorepo",
        "multi_repo_workspace": "Multi-repo workspace",
    }.get(result.classification, result.classification)
    click.echo(f"{label} (confidence: {result.confidence})")
    click.echo(f"  Root: {result.root}")
    if result.signals.get("fired"):
        click.echo(f"  Signals: {', '.join(result.signals['fired'])}")

    if result.classification == "multi_repo_workspace":
        click.echo("")
        click.echo(f"Detected repos ({len(result.repos)}):")
        for r in result.repos:
            label_part = f" — {r.display_name}" if r.display_name else ""
            git_flag = "" if r.has_git else "  (no .git)"
            click.echo(f"  - {r.rel_path}{label_part}{git_flag}")
        if result.drift_warnings:
            click.echo("")
            click.echo("AGENTS.md drift:")
            for w in result.drift_warnings:
                click.echo(f"  - {w.message}")
        click.echo("")
        click.echo(
            "Next: run `agent-readiness scan <repo>` per repo, "
            "or invoke the MCP tool `scan_workspace` to drive the "
            "selection interactively."
        )
    sys.exit(0)


@cli.command("enumerate")
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True,
                                        exists=True, path_type=Path),
                default=Path("."))
@click.option("--json", "json_output", is_flag=True,
              help="Emit the stable enumeration JSON envelope.")
def enumerate_cmd(path: Path, json_output: bool) -> None:
    """Enumerate PATH's direct children for workspace classification.

    Returns a static depth-1 view of PATH: which children look like
    code projects (have .git or README.md), their top-level files/dirs,
    a per-child language hint, and root-level monorepo-tooling signals.
    No scoring, no rules — this is the input the skill's classification
    phase consumes before deciding whether to call ``scan`` or
    ``workspace-scan``.

    Exit codes:

    \b
      0  success (including zero-child enumerations).
      2  missing path or non-directory.
    """
    import json as _json

    from agent_readiness.enumerate import enumerate_workspace

    try:
        report = enumerate_workspace(path)
    except (NotADirectoryError, FileNotFoundError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
        return

    d = report.to_dict()
    click.echo(f"root: {d['root']['path']}")
    click.echo(f"  has_git={d['root']['has_git']} "
               f"has_readme={d['root']['has_readme']} "
               f"has_agents_md={d['root']['has_agents_md']}")
    signals = [k for k, v in d["manifest_signals"].items() if v]
    if signals:
        click.echo(f"  manifest_signals: {', '.join(signals)}")
    click.echo(f"children: {len(d['children'])} "
               f"(with_git={d['stats']['children_with_git']}, "
               f"with_readme={d['stats']['children_with_readme']})")
    for c in d["children"]:
        flags = []
        if c["has_git"]:
            flags.append("git")
        if c["has_readme"]:
            flags.append("readme")
        if c["has_agents_md"]:
            flags.append("agents.md")
        click.echo(f"  - {c['path']} [{','.join(flags)}]")
    if d["stats"]["scan_truncated"]:
        click.echo("warning: enumeration truncated at 200 children", err=True)


@cli.command(name="workspace-scan")
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True,
                                        exists=True, path_type=Path))
@click.option("--children", "children_csv", type=click.STRING,
              default="",
              help="Comma-separated child paths to scan (relative or absolute).")
@click.option("--json", "json_output", is_flag=True,
              help="Emit the WorkspaceReadinessReport JSON envelope.")
def workspace_scan(path: Path, children_csv: str, json_output: bool) -> None:
    """Run a workspace-level readiness scan over PATH and its --children.

    PATH is the workspace root (where the Coordination pack runs).
    ``--children`` is a comma-separated list of child repo paths
    (absolute or relative to PATH). Both must be supplied; the skill
    is the right place to enumerate and classify before invoking this.

    Exit codes:

    \b
      0  scan completed (envelope returned regardless of overall score).
      2  PATH or any child path is missing or not a directory.
      3  --children empty or omitted.
    """
    import json as _json

    from agent_readiness.workspace_scan import scan

    if not children_csv.strip():
        click.echo("error: --children is required and must list at least one path",
                   err=True)
        sys.exit(3)

    raw = [c.strip() for c in children_csv.split(",") if c.strip()]
    children: list[Path] = []
    for c in raw:
        p = (path / c).resolve() if not Path(c).is_absolute() else Path(c).resolve()
        if not p.exists() or not p.is_dir():
            click.echo(f"error: child path is not a directory: {p}", err=True)
            sys.exit(2)
        children.append(p)

    try:
        report = scan(path, children)
    except (NotADirectoryError, FileNotFoundError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(2)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(3)

    if json_output:
        click.echo(_json.dumps(report.to_dict(), indent=2))
        return

    d = report.to_dict()
    click.echo(f"workspace: {d['repo_path']}")
    click.echo(f"overall_score: {d['overall_score']:.1f}")
    click.echo("pillars:")
    for p in d["pillars"]:
        click.echo(f"  {p['pillar']:18s} {p['score']:6.1f}  ({p['source']})")
    click.echo(f"children scanned: {d['stats']['children_scanned']} "
               f"failed: {d['stats']['children_failed']}")
    if d.get("top_action"):
        click.echo(f"top_action: {d['top_action']['check_id']} "
                   f"(scope={d['top_action']['scope']})")


@cli.group(name="manifest")
def manifest_group() -> None:
    """Inspect and validate workspace-starter manifest directories.

    A manifest directory holds the workspace bible: manifest.yaml,
    glossary.yaml, boundaries.yaml, rules/*.yaml, and an optional
    .agent-readiness-version constraint pin. See
    ``agent-readiness-manifest`` for the reference layout.
    """


@manifest_group.command(name="validate")
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True,
                                        exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True,
              help="Emit the ManifestValidationResult JSON envelope.")
@click.option("--strict", "strict", is_flag=True,
              help="Treat warnings as errors (exit non-zero if any warnings).")
def manifest_validate(path: Path, json_output: bool, strict: bool) -> None:
    """Load + validate the manifest directory at PATH.

    Runs schema validation on all four file types (manifest, glossary,
    boundaries, arch rules) AND the cross-file semantic checks
    (declared-tag-axes, arch-rule-id-vs-filename-prefix).

    Exit codes:

    \b
      0  manifest is valid (no errors; warnings ignored unless --strict).
      1  manifest is invalid (at least one error, or --strict + warnings).
      2  PATH is missing or not a directory.
    """
    import json as _json

    from agent_readiness.manifest import validate_manifest_dir

    if not path.is_dir():
        click.echo(f"error: not a directory: {path}", err=True)
        sys.exit(2)

    result = validate_manifest_dir(path)
    envelope = result.to_json_envelope()

    if json_output:
        click.echo(_json.dumps(envelope, indent=2))
    else:
        n_err  = envelope["summary"]["errors"]
        n_warn = envelope["summary"]["warnings"]
        verdict = "valid" if result.valid else "invalid"
        click.echo(
            f"manifest: {envelope['summary']['manifest_name'] or '?'}  "
            f"{verdict}  ({n_err} error(s), {n_warn} warning(s))"
        )
        for issue in result.issues:
            click.echo(f"  [{issue.severity:5s}] {issue.message}  ({issue.location})")

    has_warn = any(i.severity == "warn" for i in result.issues)
    if not result.valid or (strict and has_warn):
        sys.exit(1)


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


@cli.group()
def ontology() -> None:
    """Workspace Ontology subcommands."""


@ontology.command("load")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path, exists=False),
)
@click.option("--json", "json_output", is_flag=True, help="Emit compact JSON (default: pretty).")
def ontology_load(path: Path, json_output: bool) -> None:
    """Load an ontology/ directory and print its contents.

    PATH is the path to the `ontology/` directory itself (not the workspace root).
    Missing PATH yields an empty Ontology with exit code 0; malformed YAML
    or schema violations exit with code 1.
    """
    import json as _json

    from agent_readiness.ontology import load_ontology

    try:
        ont = load_ontology(path)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(1)

    def _dump_types(d: dict) -> dict:
        return {name: model.model_dump(mode="json") for name, model in d.items()}

    def _dump_instances(d: dict) -> dict:
        return {
            type_name: [inst.model_dump(mode="json") for inst in insts]
            for type_name, insts in d.items()
        }

    payload = {
        "object_types": _dump_types(ont.object_types),
        "link_types": _dump_types(ont.link_types),
        "interfaces": _dump_types(ont.interfaces),
        "functions": _dump_types(ont.functions),
        "action_types": _dump_types(ont.action_types),
        "intent_types": _dump_types(ont.intent_types),
        "object_instances": _dump_instances(ont.object_instances),
        "link_instances": _dump_instances(ont.link_instances),
    }

    if json_output:
        click.echo(_json.dumps(payload, separators=(",", ":")))
    else:
        click.echo(_json.dumps(payload, indent=2))


if __name__ == "__main__":
    cli()
