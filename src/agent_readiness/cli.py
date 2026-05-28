"""Command-line interface for agent-readiness (click-based)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

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


def _launch_dashboard_with_onboarding(
    path: Path,
    committed_type: str,  # WorkspaceType literal
    now,  # datetime; injectable for tests
    no_open: bool = False,
) -> dict:
    """Create a scan_id, write onboarding.json, start the HTTP server,
    return the dashboard URL pointing at /onboarding/<scan_id>.

    Shared by `scan-repo`, `scan-monorepo`, `scan-workspace`. The wizard
    in the dashboard reads onboarding.json and renders the appropriate
    step strip based on `committed_type`."""
    import uuid

    from agent_readiness.enumerate_git import inspect as do_inspect
    from agent_readiness.live_scan.server import start_server
    from agent_readiness.onboarding import (
        OnboardingState,
        path_for,
        save,
    )

    # Stable scan_id: <basename>-<6 hex chars>.
    suffix = uuid.uuid4().hex[:6]
    scan_id = f"{path.resolve().name}-{suffix}"
    scan_dir = path_for(scan_id)
    scan_dir.mkdir(parents=True, exist_ok=True)

    # Run enumeration + classification synchronously (fast, ≤200ms target).
    inspect_result = do_inspect(path)

    # Persist OnboardingState with committed_type from the subcommand.
    state = OnboardingState(
        scan_id=scan_id,
        committed_type=committed_type,
        enumeration=inspect_result.enumeration,
        classification=inspect_result.classification,
        selection=None,
        created_at=now,
    )
    save(scan_dir, state)

    # Start the HTTP server (idempotent — returns existing port if up).
    srv = start_server(
        host="127.0.0.1",
        port=0,
        data_dir=scan_dir,
        workspace_path=path.expanduser().resolve(),
    )
    base = f"http://{srv.host}:{srv.port}"
    dashboard_url = f"{base}/#/onboarding/{scan_id}"

    if not no_open:
        import webbrowser
        webbrowser.open(dashboard_url)

    return {
        "status": "onboarding_required",
        "scan_id": scan_id,
        "dashboard_url": dashboard_url,
        "type": committed_type,
        "message": "Onboarding wizard opened. Pick repos and confirm to start scan.",
    }


@cli.command("inspect")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Emit InspectResult as JSON.")
def inspect_cmd(path: Path, json_output: bool) -> None:
    """Enumerate ``PATH`` and suggest a workspace type.

    Fast pre-flight for the skill / agent before calling one of the
    typed scan subcommands (``scan-repo``, ``scan-monorepo``,
    ``scan-workspace``).
    """
    from agent_readiness.enumerate_git import inspect as do_inspect

    result = do_inspect(path)
    if json_output:
        click.echo(result.model_dump_json(indent=2))
        return
    enum = result.enumeration
    cls = result.classification
    click.echo(f"Path:                {enum.root}")
    click.echo(f"Git repos found:     {len(enum.repos)}")
    click.echo(f"Root has .git:       {enum.root_has_git}")
    click.echo(f"Directories walked:  {enum.directories_walked}")
    click.echo(f"Elapsed:             {enum.elapsed_ms}ms")
    click.echo()
    click.echo(f"Suggested type:      {cls.suggested_type}")
    click.echo(f"Confidence:          {cls.confidence}")
    click.echo(f"Rationale:           {cls.rationale}")


@cli.command("scan-repo")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Emit started envelope as JSON.")
@click.option("--no-open", is_flag=True, help="Do not auto-open the browser.")
def scan_repo_cmd(path: Path, json_output: bool, no_open: bool) -> None:
    """Score ``PATH`` as a single repository.

    Opens the dashboard at ``/onboarding/<scan_id>`` so the user can
    confirm and hit Start. The wizard for single_repo is 2 steps
    (Detected → Start) — no picker."""
    import json
    from datetime import datetime, timezone

    result = _launch_dashboard_with_onboarding(
        path=path,
        committed_type="single_repo",
        now=datetime.now(timezone.utc),
        no_open=no_open,
    )
    if json_output:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Onboarding wizard: {result['dashboard_url']}")
        click.echo("Confirm the suggestion and hit Start to begin scanning.")


@cli.command("scan-monorepo")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
@click.option("--no-open", is_flag=True)
def scan_monorepo_cmd(path: Path, json_output: bool, no_open: bool) -> None:
    """Score ``PATH`` as a monorepo (one .git at root, many packages inside).

    Opens the wizard with Detected → Pick (grouped by parent folder) → Start.
    All detected packages pre-selected by default."""
    import json
    from datetime import datetime, timezone

    result = _launch_dashboard_with_onboarding(
        path=path,
        committed_type="monorepo",
        now=datetime.now(timezone.utc),
        no_open=no_open,
    )
    if json_output:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Onboarding wizard: {result['dashboard_url']}")
        click.echo("Pick which packages to score, then hit Start.")


@cli.command("scan-workspace")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
@click.option("--no-open", is_flag=True)
def scan_workspace_cmd(path: Path, json_output: bool, no_open: bool) -> None:
    """Score ``PATH`` as a workspace of independent repos.

    Opens the wizard with Detected → Pick (flat grid) → Start. All
    children with .git pre-selected."""
    import json
    from datetime import datetime, timezone

    result = _launch_dashboard_with_onboarding(
        path=path,
        committed_type="workspace",
        now=datetime.now(timezone.utc),
        no_open=no_open,
    )
    if json_output:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Onboarding wizard: {result['dashboard_url']}")
        click.echo("Pick which repos to scan, then hit Start.")


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


@cli.group(name="gap")
def gap_group() -> None:
    """Manage gaps, clarifications, and assumptions recorded by agents.

    Reads/writes ``.agent-readiness/gaps.jsonl`` in the current
    working directory (the workspace root). Append-only JSONL with
    one record per line, written by:

    * the MCP server's ``record_gap_tool`` / ``ask_clarification_tool`` /
      ``log_assumption_tool`` (the typical path — agents call these
      during a session when they recognise they can't confidently
      proceed),
    * ``agent-readiness gap record`` (this subcommand, for manual
      capture and for tests).

    Unresolved Gap rows surface as findings on the next
    ``agent-readiness scan`` via the ``ontology.gaps_unresolved``
    rule and cost workspace score until a human reviewer runs
    ``agent-readiness gap resolve <id>``. Clarification and
    Assumption rows never cost score (they're informational).
    """


@gap_group.command(name="record")
@click.option(
    "--kind",
    required=True,
    help=(
        "Agent's classification of what was ambiguous "
        "(e.g. 'ambiguous_object_type', 'missing_manifest_field')."
    ),
)
@click.option(
    "--detail",
    required=True,
    help="One-paragraph human-readable description of the gap.",
)
@click.option(
    "--severity",
    type=click.Choice(["low", "medium", "high"]),
    default="medium",
    show_default=True,
    help="Agent's self-assessed urgency. Maps to the emitted finding's severity.",
)
@click.option(
    "--candidate",
    "candidates",
    multiple=True,
    help="Candidate resolution the agent considered. Repeatable.",
)
@click.option(
    "--agent-session",
    default=None,
    help="Optional opaque session id from the recording agent.",
)
def gap_record(
    kind: str,
    detail: str,
    severity: str,
    candidates: tuple[str, ...],
    agent_session: str | None,
) -> None:
    """Record a new gap in ``.agent-readiness/gaps.jsonl``."""
    from agent_readiness.gaps import record_gap

    new_id = record_gap(
        kind=kind,
        detail=detail,
        severity=severity,
        candidate_resolutions=list(candidates),
        agent_session=agent_session,
    )
    click.echo(f"recorded gap {new_id}")


@gap_group.command(name="list")
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show resolved gaps too (default: unresolved only).",
)
def gap_list(show_all: bool) -> None:
    """List gaps from ``.agent-readiness/gaps.jsonl``."""
    from agent_readiness.gaps import list_gaps

    gaps = list_gaps(include_resolved=show_all)
    if not gaps:
        click.echo(
            "no unresolved gaps." if not show_all else "no gaps recorded."
        )
        return
    for g in gaps:
        marker = "x" if g.get("resolved") else " "
        gap_kind = g.get("gap_kind", "<no-kind>")
        detail = g.get("detail", "<no detail>")
        click.echo(f"[{marker}] {g['id']}  {gap_kind}  {detail}")


@gap_group.command(name="resolve")
@click.argument("gap_id")
def gap_resolve(gap_id: str) -> None:
    """Mark a gap as resolved."""
    from agent_readiness.gaps import resolve_gap

    if resolve_gap(gap_id):
        click.echo(f"resolved {gap_id}")
    else:
        click.echo(f"no such gap: {gap_id}", err=True)
        raise click.exceptions.Exit(1)


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


def _emit_payload(payload: Any, json_output: bool) -> None:
    import json as _json

    if json_output:
        click.echo(_json.dumps(payload, separators=(",", ":")))
    else:
        click.echo(_json.dumps(payload, indent=2))


def _parse_kv_pairs(pairs: tuple[str, ...]) -> dict[str, Any]:
    """Parse ``--where k=v --where k2=v2`` into a dict.

    Values are JSON-parsed when possible, otherwise kept as strings.
    """
    import json as _json

    out: dict[str, Any] = {}
    for kv in pairs:
        if "=" not in kv:
            raise click.UsageError(f"Expected K=V, got {kv!r}")
        k, v = kv.split("=", 1)
        try:
            out[k] = _json.loads(v)
        except _json.JSONDecodeError:
            out[k] = v
    return out


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


@ontology.group("bootstrap")
def ontology_bootstrap() -> None:
    """Bootstrap the workspace ontology."""


@ontology_bootstrap.command("init")
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True, path_type=Path))
@click.option(
    "--profile",
    type=click.Choice(["workspace", "single-repo", "monorepo"]),
    default="workspace",
)
@click.option(
    "--manifest-template",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
)
@click.option("--json", "json_output", is_flag=True)
def ontology_bootstrap_init(
    path: Path,
    profile: str,
    manifest_template: Path | None,
    json_output: bool,
) -> None:
    """Scaffold an empty ontology/ skeleton from the starter template."""
    from agent_readiness.ontology.bootstrap import init_ontology

    try:
        report = init_ontology(path, profile=profile, manifest_template=manifest_template)
    except FileExistsError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(1)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    payload = {
        "files_written": report.files_written,
        "profile": report.profile,
        "skipped_due_to_profile": report.skipped_due_to_profile,
    }
    _emit_payload(payload, json_output)


@ontology_bootstrap.command("propose-objects")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
)
@click.option("--object-type", required=True)
@click.option("--json", "json_output", is_flag=True)
def ontology_bootstrap_propose_objects(
    path: Path, object_type: str, json_output: bool
) -> None:
    """Propose Object Type instances from observed workspace signals."""
    from agent_readiness.ontology.bootstrap import propose_object_instances

    try:
        env = propose_object_instances(workspace=path, object_type=object_type)
    except (NotImplementedError, ValueError) as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    _emit_payload(env.model_dump(mode="json"), json_output)


@ontology_bootstrap.command("propose-links")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
)
@click.option("--link-type", required=True)
@click.option("--min-ratified-pct", type=float, default=0.8)
@click.option("--json", "json_output", is_flag=True)
def ontology_bootstrap_propose_links(
    path: Path, link_type: str, min_ratified_pct: float, json_output: bool
) -> None:
    """Propose Link Type instances from observed workspace signals."""
    from agent_readiness.ontology.bootstrap import propose_link_instances

    try:
        env = propose_link_instances(
            path, link_type=link_type, min_ratified_pct=min_ratified_pct
        )
    except RuntimeError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    except (NotImplementedError, ValueError) as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    _emit_payload(env.model_dump(mode="json"), json_output)


@ontology_bootstrap.command("propose-interfaces")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
)
@click.option("--interface", required=True)
@click.option("--json", "json_output", is_flag=True)
def ontology_bootstrap_propose_interfaces(
    path: Path, interface: str, json_output: bool
) -> None:
    """Propose interface claims from observed workspace signals."""
    from agent_readiness.ontology.bootstrap import propose_interface_claims

    try:
        env = propose_interface_claims(workspace=path, interface=interface)
    except (NotImplementedError, ValueError) as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    _emit_payload(env.model_dump(mode="json"), json_output)


@ontology_bootstrap.command("propose-functions")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
)
@click.option("--function-type", required=True)
@click.option("--json", "json_output", is_flag=True)
def ontology_bootstrap_propose_functions(
    path: Path, function_type: str, json_output: bool
) -> None:
    """Propose function implementations from observed workspace signals."""
    from agent_readiness.ontology.bootstrap import propose_function_implementations

    try:
        env = propose_function_implementations(workspace=path, function_type=function_type)
    except (NotImplementedError, ValueError) as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    _emit_payload(env.model_dump(mode="json"), json_output)


@ontology_bootstrap.command("propose-actions")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
)
@click.option("--scope", default="all")
@click.option("--json", "json_output", is_flag=True)
def ontology_bootstrap_propose_actions(
    path: Path, scope: str, json_output: bool
) -> None:
    """Propose action and intent types from observed workspace signals."""
    from agent_readiness.ontology.bootstrap import propose_action_intent_types

    try:
        env = propose_action_intent_types(workspace=path, scope=scope)
    except (NotImplementedError, ValueError) as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    _emit_payload(env.model_dump(mode="json"), json_output)


@ontology.command("ratify")
@click.argument("atom_id")
@click.option("--ratified-by", required=True)
@click.option(
    "--workspace",
    "workspace",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
def ontology_ratify(atom_id: str, ratified_by: str, workspace: Path) -> None:
    """Bump a proposed atom's lifecycle.state to ratified."""
    from agent_readiness.ontology.ratify import ratify_atom

    try:
        path = ratify_atom(workspace, atom_id, ratified_by)
    except LookupError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(1)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    click.echo(f"ratified: {atom_id} ({path})")


@ontology.command("validate")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("ontology"),
)
@click.option("--strict", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def ontology_validate(path: Path, strict: bool, json_output: bool) -> None:
    """Validate the ontology. With --strict, enforce closure invariant."""
    from agent_readiness.ontology.validate import validate_ontology

    rep = validate_ontology(path, strict=strict)
    payload = {
        "ok": rep.ok,
        "issues": [
            {"kind": i.kind, "atom_id": i.atom_id, "message": i.message}
            for i in rep.issues
        ],
    }
    _emit_payload(payload, json_output)
    if not rep.ok:
        raise SystemExit(1)


@ontology.command("query")
@click.argument("expr")
@click.option(
    "--workspace",
    "workspace",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--json", "json_output", is_flag=True)
def ontology_query(expr: str, workspace: Path, json_output: bool) -> None:
    """Run a simple query against the ontology. See --help for the grammar."""
    from agent_readiness.ontology.query import query_ontology

    try:
        result = query_ontology(workspace / "ontology", expr)
    except ValueError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    _emit_payload({"expr": expr, "result": result}, json_output)


@ontology.command("status")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("ontology"),
)
@click.option("--json", "json_output", is_flag=True)
def ontology_status(path: Path, json_output: bool) -> None:
    """Per-type summary: declared, proposed, ratified."""
    from agent_readiness.ontology.status import status_ontology

    rep = status_ontology(path)
    payload = {
        "object_types": {
            name: {
                "declared": ts.declared,
                "proposed": ts.proposed_instances,
                "ratified": ts.ratified_instances,
            }
            for name, ts in rep.object_types.items()
        },
        "link_types": {
            name: {
                "declared": ts.declared,
                "proposed": ts.proposed_instances,
                "ratified": ts.ratified_instances,
            }
            for name, ts in rep.link_types.items()
        },
        "interfaces_declared": rep.interfaces_declared,
        "functions_declared": rep.functions_declared,
        "action_types_declared": rep.action_types_declared,
        "intent_types_declared": rep.intent_types_declared,
    }
    _emit_payload(payload, json_output)


@ontology.command("list-object-types")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--json", "json_output", is_flag=True)
def ontology_list_object_types(path: Path, json_output: bool) -> None:
    """List declared ObjectType definitions."""
    from agent_readiness.ontology.runtime import list_object_types

    _emit_payload(list_object_types(path), json_output)


@ontology.command("query-objects")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--object-type", required=True)
@click.option("--where", multiple=True, help="Property filter as K=V (repeatable).")
@click.option("--json", "json_output", is_flag=True)
def ontology_query_objects(
    path: Path, object_type: str, where: tuple[str, ...], json_output: bool
) -> None:
    """Query ratified ObjectInstances by type and optional property filters."""
    from agent_readiness.ontology.runtime import query_objects

    _emit_payload(
        query_objects(path, object_type=object_type, where=_parse_kv_pairs(where) or None),
        json_output,
    )


@ontology.command("list-links")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--from", "from_id", default=None, help="Filter by source object id.")
@click.option("--to", "to_id", default=None, help="Filter by target object id.")
@click.option("--link-type", default=None, help="Filter by link type name.")
@click.option("--json", "json_output", is_flag=True)
def ontology_list_links(
    path: Path,
    from_id: str | None,
    to_id: str | None,
    link_type: str | None,
    json_output: bool,
) -> None:
    """List ratified LinkInstances with optional filters."""
    from agent_readiness.ontology.runtime import list_links

    _emit_payload(
        list_links(path, from_id=from_id, to_id=to_id, link_type=link_type),
        json_output,
    )


@ontology.command("get-object")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--id", "object_id", required=True, help="Object instance id.")
@click.option("--json", "json_output", is_flag=True)
def ontology_get_object(path: Path, object_id: str, json_output: bool) -> None:
    """Fetch a single ratified ObjectInstance by id."""
    from agent_readiness.ontology.runtime import get_object

    obj = get_object(path, object_id)
    _emit_payload(obj, json_output)
    if obj is None:
        raise SystemExit(1)


@ontology.command("list-interfaces")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--json", "json_output", is_flag=True)
def ontology_list_interfaces(path: Path, json_output: bool) -> None:
    """List declared InterfaceType definitions."""
    from agent_readiness.ontology.runtime import list_interfaces

    _emit_payload(list_interfaces(path), json_output)


@ontology.command("which-interfaces")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--object-id", required=True, help="Object instance id.")
@click.option("--json", "json_output", is_flag=True)
def ontology_which_interfaces(
    path: Path, object_id: str, json_output: bool
) -> None:
    """List interface claims on a ratified ObjectInstance."""
    from agent_readiness.ontology.runtime import which_interfaces

    _emit_payload(which_interfaces(path, object_id), json_output)


@ontology.command("list-functions")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--json", "json_output", is_flag=True)
def ontology_list_functions(path: Path, json_output: bool) -> None:
    """List declared FunctionType definitions and implementation status."""
    from agent_readiness.ontology.runtime import list_functions

    _emit_payload(list_functions(path), json_output)


@ontology.command("invoke-function")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--function-name", required=True)
@click.option("--arg", "args", multiple=True, help="Function argument as K=V (repeatable).")
@click.option("--json", "json_output", is_flag=True)
def ontology_invoke_function(
    path: Path, function_name: str, args: tuple[str, ...], json_output: bool
) -> None:
    """Invoke an ontology function implementation."""
    from agent_readiness.ontology.runtime import (
        FunctionInvocationError,
        FunctionNotFoundError,
        invoke_function,
    )

    try:
        result = invoke_function(path, function_name, **_parse_kv_pairs(args))
    except FunctionNotFoundError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(1)
    except FunctionInvocationError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    _emit_payload(result, json_output)


@ontology.command("apply-action")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--action-id", required=True)
@click.option("--arg", "args", multiple=True, help="Action argument as K=V (repeatable).")
@click.option("--no-dry-run", "no_dry_run", is_flag=True, default=False)
@click.option("--json", "json_output", is_flag=True)
def ontology_apply_action(
    path: Path,
    action_id: str,
    args: tuple[str, ...],
    no_dry_run: bool,
    json_output: bool,
) -> None:
    """Apply a declared ActionType (dry-run by default)."""
    from agent_readiness.ontology.runtime import (
        ActionExecutionError,
        ActionNotFoundError,
        apply_action,
    )

    try:
        result = apply_action(
            path,
            action_id,
            _parse_kv_pairs(args),
            dry_run=not no_dry_run,
        )
    except ActionNotFoundError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(1)
    except ActionExecutionError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    _emit_payload(result, json_output)


@ontology.command("record-intent")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--intent-type", required=True)
@click.option("--goal-arg", "goal_args", multiple=True, help="Goal argument as K=V.")
@click.option("--started-by", default=lambda: os.getenv("USER", "agent"))
@click.option("--json", "json_output", is_flag=True)
def ontology_record_intent(
    path: Path,
    intent_type: str,
    goal_args: tuple[str, ...],
    started_by: str,
    json_output: bool,
) -> None:
    """Record a new cross-repo intent without executing steps."""
    from agent_readiness.ontology.runtime import IntentNotFoundError, record_intent

    try:
        result = record_intent(
            path,
            intent_type,
            _parse_kv_pairs(goal_args),
            started_by,
        )
    except IntentNotFoundError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(1)
    _emit_payload(result, json_output)


@ontology.command("advance-intent")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--intent-id", required=True)
@click.option("--step-id", required=True)
@click.option("--no-dry-run", "no_dry_run", is_flag=True, default=False)
@click.option("--json", "json_output", is_flag=True)
def ontology_advance_intent(
    path: Path,
    intent_id: str,
    step_id: str,
    no_dry_run: bool,
    json_output: bool,
) -> None:
    """Advance one intent step (dry-run by default)."""
    from agent_readiness.ontology.runtime import (
        IntentNotFoundError,
        IntentStepError,
        advance_intent,
    )

    try:
        result = advance_intent(
            path,
            intent_id,
            step_id,
            dry_run=not no_dry_run,
        )
    except IntentNotFoundError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(1)
    except IntentStepError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(2)
    _emit_payload(result, json_output)


@ontology.command("query-intent")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--intent-id", required=True)
@click.option("--json", "json_output", is_flag=True)
def ontology_query_intent(path: Path, intent_id: str, json_output: bool) -> None:
    """Query consolidated intent state from the ledger."""
    from agent_readiness.ontology.runtime import IntentNotFoundError, query_intent

    try:
        result = query_intent(path, intent_id)
    except IntentNotFoundError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(1)
    _emit_payload(result, json_output)


@ontology.command("list-active-intents")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--json", "json_output", is_flag=True)
def ontology_list_active_intents(path: Path, json_output: bool) -> None:
    """List intents that still have pending steps."""
    from agent_readiness.ontology.runtime import list_active_intents

    _emit_payload(list_active_intents(path), json_output)


@ontology.command("drift")
@click.argument(
    "workspace",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option("--json", "json_output", is_flag=True)
@click.option(
    "--block-threshold",
    type=int,
    default=70,
    help=(
        "Severity score at which CLI exits 2 (block); default 70 "
        "(matches DriftReport.severity_level=='block')."
    ),
)
def ontology_drift(workspace: Path, json_output: bool, block_threshold: int) -> None:
    """Compute drift between ratified ontology and observed workspace reality."""
    from agent_readiness.ontology.drift.detect import detect_drift

    report = detect_drift(workspace)
    payload = report.model_dump(mode="json")
    _emit_payload(payload, json_output)
    if report.severity_score >= block_threshold:
        raise SystemExit(2)
    if report.deltas:
        raise SystemExit(1)


@ontology.command("drift-propose-pr")
@click.argument(
    "workspace",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option(
    "--manifest",
    "manifest",
    required=True,
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
)
@click.option(
    "--apply/--dry-run",
    default=False,
    help=(
        "--apply writes to the manifest repo + creates branch. "
        "--dry-run is default."
    ),
)
@click.option(
    "--skip-gh/--with-gh",
    default=True,
    help="Don't actually call gh pr create (default: True for safety).",
)
@click.option("--json", "json_output", is_flag=True)
def ontology_drift_propose_pr(
    workspace: Path,
    manifest: Path,
    apply: bool,
    skip_gh: bool,
    json_output: bool,
) -> None:
    """Open a PR against the manifest repo with proposed ontology updates from drift."""
    from agent_readiness.ontology.drift.detect import detect_drift
    from agent_readiness.ontology.drift.propose_pr import propose_pr_for_drift

    report = detect_drift(workspace)
    result = propose_pr_for_drift(
        report=report,
        manifest_repo=manifest,
        dry_run=not apply,
        skip_gh=skip_gh,
    )
    payload = {
        "pr_url": result.pr_url,
        "branch": result.branch,
        "yaml_diff": result.yaml_diff,
        "files_created": [str(p) for p in result.files_created],
        "files_modified": [str(p) for p in result.files_modified],
        "files_deleted": [str(p) for p in result.files_deleted],
        "severity_level": report.severity_level,
        "severity_score": report.severity_score,
    }
    _emit_payload(payload, json_output)


@ontology.command("reason")
@click.argument(
    "workspace",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
    default=Path("."),
)
@click.option(
    "--rule",
    "rule_id",
    default=None,
    help=(
        "Run only the named inference rule "
        "(e.g. ontology.inference.acyclic_dependsOn). "
        "Default: run all registered evaluators."
    ),
)
@click.option(
    "--ontology-root",
    "ontology_root",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help=(
        "Override the ontology/ directory. Default: <workspace>/ontology, "
        "falling back to <workspace>/agent-readiness-manifest/ontology."
    ),
)
@click.option("--json", "json_output", is_flag=True, default=True, show_default=True)
def ontology_reason(
    workspace: Path,
    rule_id: str | None,
    ontology_root: Path | None,
    json_output: bool,
) -> None:
    """Run the ontology forward chainer; emit derived violations.

    Loads the workspace ontology, runs every registered inference
    evaluator (or just the one named via ``--rule``), and prints the
    list of :class:`DerivedViolation` records as JSON. Designed for
    headless consumption: 1:1 with the
    ``reason_over_ontology`` MCP tool shipped by
    ``agent-readiness-ontology-mcp`` v0.2.0+.

    Exits 0 even when violations are present — the CLI's job is to
    surface them, not gate on them. ``agent-readiness scan`` is the
    path that turns these into scored findings via the
    ``ontology.inference.*`` rules.
    """

    from agent_readiness.ontology import load_ontology
    from agent_readiness.ontology.reasoning import (
        REGISTRY,
        run_inference,
        violation_to_dict,
    )

    if ontology_root is None:
        candidate_in_repo = workspace / "ontology"
        candidate_umbrella = workspace / "agent-readiness-manifest" / "ontology"
        if candidate_in_repo.is_dir():
            ontology_root = candidate_in_repo
        elif candidate_umbrella.is_dir():
            ontology_root = candidate_umbrella
        else:
            payload: dict[str, Any] = {
                "violations": [],
                "rule_filter": rule_id,
                "registered_rules": sorted(REGISTRY.evaluators.keys()),
                "warning": (
                    f"no ontology/ found at {candidate_in_repo} or "
                    f"{candidate_umbrella}; nothing to reason over"
                ),
            }
            _emit_payload(payload, json_output)
            return

    ont = load_ontology(ontology_root)
    violations = run_inference(ont, rule_filter=rule_id)
    payload = {
        "ontology_root": str(ontology_root),
        "rule_filter": rule_id,
        "registered_rules": sorted(REGISTRY.evaluators.keys()),
        "violations": [violation_to_dict(v) for v in violations],
    }
    _emit_payload(payload, json_output)


# ---------- live-scan commands (Plan 1) -------------------------------------

import time as _time  # noqa: E402
import webbrowser as _webbrowser  # noqa: E402

from agent_readiness.live_scan import discovery as _discovery  # noqa: E402
from agent_readiness.live_scan import paths as _paths  # noqa: E402
from agent_readiness.live_scan.pidfile import (  # noqa: E402
    PidStatus as _PidStatus,
)
from agent_readiness.live_scan.pidfile import (  # noqa: E402
    clear_pidfile as _clear_pidfile,
)
from agent_readiness.live_scan.pidfile import (  # noqa: E402
    verify_pidfile as _verify_pidfile,
)
from agent_readiness.live_scan.pidfile import (  # noqa: E402
    write_pidfile as _write_pidfile,
)
from agent_readiness.live_scan.paths import workspace_hash as _workspace_hash  # noqa: E402
from agent_readiness.live_scan.events import EventLog as _EventLog  # noqa: E402
from agent_readiness.live_scan.server import start_server as _start_server  # noqa: E402
from agent_readiness.live_scan.worker import ScanOptions as _ScanOptions  # noqa: E402
from agent_readiness.live_scan.worker import scan_workspace as _scan_workspace  # noqa: E402
from agent_readiness.render import export_report as _export_report  # noqa: E402


@cli.command(name="scan-and-view")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True)
@click.option("--no-open", is_flag=True)
@click.option("--children", default=None, help="Deprecated; ignored.")
def scan_and_view_cmd(path: Path, json_output: bool, no_open: bool, children: str | None) -> None:
    """[DEPRECATED] Use `scan-repo`, `scan-monorepo`, or `scan-workspace`.

    Kept for backward compat for one release. Dispatches to
    `scan-workspace` (the closest historical behavior — multi-repo scan
    with grid layout). Will be removed in v5.0.0.
    """
    import json
    from datetime import datetime, timezone

    click.echo(
        "DEPRECATED: `scan-and-view` is replaced by `scan-repo`, "
        "`scan-monorepo`, or `scan-workspace` (plan 2 / v4.0.0). "
        "Dispatching to `scan-workspace` for compatibility.",
        err=True,
    )
    if children is not None:
        click.echo(
            "NOTE: --children is ignored. Use the wizard's Pick step in "
            "the browser to choose repos.",
            err=True,
        )
    result = _launch_dashboard_with_onboarding(
        path=path,
        committed_type="workspace",
        now=datetime.now(timezone.utc),
        no_open=no_open,
    )
    if json_output:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Onboarding wizard: {result['dashboard_url']}")


@cli.command(name="scan-status")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
)
@click.option("--json", "json_output", is_flag=True, default=False)
def scan_status(path: Path, json_output: bool) -> None:
    """Print status of a workspace's most recent scan."""
    import json as _j
    sd = _paths.scan_dir(path)
    live = sd / "live.json"
    latest = sd / "latest.json"
    target = live if live.exists() else latest if latest.exists() else None
    if target is None:
        click.echo("No scan history for this workspace.", err=True)
        raise click.exceptions.Exit(1)
    data = _j.loads(target.read_text())
    if json_output:
        click.echo(_j.dumps(data, indent=2))
    else:
        click.echo(f"status: {data.get('status')}")
        click.echo(f"progress: {data.get('progress')}")
        click.echo(f"overall: {data.get('overall_score')}")


@cli.command(name="scan-stop")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    required=False,
)
@click.option("--all", "all_flag", is_flag=True, default=False)
def scan_stop(path: Path | None, all_flag: bool) -> None:
    """Stop a running scan (one workspace, or ``--all``)."""
    import json as _j
    import signal as _sig
    if all_flag:
        result = _discovery.stop_all()
        killed = result.get("killed", [])
        skipped = result.get("skipped", [])
        click.echo(
            f"Stopped {len(killed)} scans: {', '.join(killed) or '(none)'}"
        )
        for s in skipped:
            click.echo(f"Skipped {s['scan_id']} ({s['reason']})")
        return
    if path is None:
        raise click.UsageError("provide PATH or --all")
    sd = _paths.scan_dir(path)
    pid_path = sd / "daemon.pid"
    status = _verify_pidfile(pid_path)
    if status is not _PidStatus.LIVE:
        click.echo(f"No live scan ({status.value}).", err=True)
        _clear_pidfile(pid_path)
        raise click.exceptions.Exit(1)
    data = _j.loads(pid_path.read_text())
    os.kill(data["pid"], _sig.SIGTERM)
    click.echo(f"Sent SIGTERM to {data['pid']}.")


@cli.command(name="scan-list")
@click.option("--json", "json_output", is_flag=True, default=False)
def scan_list(json_output: bool) -> None:
    """Enumerate active + recent scans across all workspaces."""
    import json as _j
    result = _discovery.list_scans()
    if json_output:
        click.echo(_j.dumps(result, indent=2))
        return
    active = result.get("active", [])
    recent = result.get("recent", [])
    click.echo(f"ACTIVE ({len(active)}):")
    for s in active:
        click.echo(
            f"  {s['scan_id']:20s} "
            f"{s.get('workspace_path') or '?':40s} "
            f"{s.get('dashboard_url') or ''}"
        )
    click.echo("\nRECENT (last 50, top 10):")
    for s in recent[:10]:
        overall = s.get("overall_score")
        overall_s = f"{overall:.1f}" if isinstance(overall, (int, float)) else "?"
        click.echo(
            f"  {s['scan_id']:20s} "
            f"{s.get('workspace_path') or '?':40s} "
            f"{overall_s:>6}  {s.get('completed_at') or '?'}"
        )
    mb = result.get("total_disk_bytes", 0) / 1024 / 1024
    click.echo(
        f"\nTotal disk: {mb:.1f} MB across "
        f"{len(active) + len(recent)} workspaces"
    )


@cli.command(name="render-report")
@click.argument(
    "path",
    type=click.Path(file_okay=False, dir_okay=True, exists=True, path_type=Path),
)
@click.option(
    "--scan-id", "scan_id", default=None,
    help="Specific scan to render (default: live or latest).",
)
@click.option(
    "--output-dir", "output_dir",
    type=click.Path(path_type=Path), default=None,
)
@click.option("--json", "json_output", is_flag=True, default=False)
def render_report_cmd(
    path: Path,
    scan_id: str | None,
    output_dir: Path | None,
    json_output: bool,
) -> None:
    """Render a scan as a portable static directory."""
    import json as _j
    result = _export_report(path, scan_id=scan_id, output_dir=output_dir)
    if json_output:
        click.echo(_j.dumps({
            "status": "rendered",
            "index_path": str(result.index_path),
            "output_dir": str(result.output_dir),
            "scan_id": result.scan_id,
            "scan_ts": result.scan_ts,
            "rendered_at": result.rendered_at,
            "source_status": result.source_status,
        }, indent=2))
    else:
        click.echo(str(result.index_path))


if __name__ == "__main__":
    cli()
