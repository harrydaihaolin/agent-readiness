"""scaffold.py — generate missing agent-readiness files from templates.

Called by `agent-readiness scaffold [PATH] [--dry-run] [--force] [--only]`.
Fully headless: no interactive prompts. Use --dry-run to preview.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from agent_readiness.checks import _ensure_loaded, all_checks
from agent_readiness.context import RepoContext


# Maps check_id → list of (relative_dest, template_name) tuples.
# Each entry describes one file this check requires.
_CHECK_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "agent_docs.present": [
        ("AGENTS.md", "AGENTS.md"),
    ],
    "devcontainer.present": [
        (".devcontainer/devcontainer.json", "devcontainer.json"),
    ],
    "templates.present": [
        (".github/ISSUE_TEMPLATE/bug_report.md", "issue_template_bug.md"),
        (".github/ISSUE_TEMPLATE/feature_request.md", "issue_template_feature.md"),
        (".github/pull_request_template.md", "pull_request_template.md"),
        ("CODEOWNERS", "CODEOWNERS"),
    ],
    "hooks.configured": [
        (".pre-commit-config.yaml", "pre-commit-config.yaml"),
    ],
    "security.dependabot_configured": [
        (".github/dependabot.yml", "dependabot.yml"),
    ],
    "security.policy_present": [
        ("SECURITY.md", "SECURITY.md"),
    ],
    "gitignore.covers_junk": [
        (".gitignore", "gitignore"),
    ],
}


def _load_template(name: str) -> str:
    """Load a template by filename from the bundled templates directory."""
    try:
        from importlib.resources import files
        template_text = (files("agent_readiness") / "templates" / name).read_text(encoding="utf-8")
        return template_text
    except (FileNotFoundError, TypeError, ModuleNotFoundError):
        # Fallback: locate relative to this file
        here = Path(__file__).parent
        template_path = here / "templates" / name
        if template_path.is_file():
            return template_path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Template not found: {name}")


def _substitute(text: str, ctx: RepoContext) -> str:
    """Replace {{PLACEHOLDERS}} in template text with repo-specific values."""
    repo_name = ctx.root.name
    return (
        text
        .replace("{{REPO_NAME}}", repo_name)
        .replace("{{PROJECT_NAME}}", repo_name)
    )


def run_scaffold(
    path: Path,
    dry_run: bool = False,
    force: bool = False,
    only_checks: str | None = None,
) -> None:
    """Main entry point for the scaffold command."""
    from agent_readiness.plugins import load_entry_point_plugins, load_local_plugins
    load_local_plugins(path)
    load_entry_point_plugins()
    _ensure_loaded()

    ctx = RepoContext(root=path)
    specs = all_checks()

    # Filter by --only if requested
    filter_ids: set[str] | None = None
    if only_checks:
        filter_ids = {t.strip() for t in only_checks.split(",")}

    # Run checks to find which ones are failing
    failing_ids: set[str] = set()
    for spec in specs:
        if filter_ids and spec.check_id not in filter_ids:
            continue
        if spec.check_id not in _CHECK_TEMPLATES:
            continue
        result = spec.fn(ctx)
        if not result.not_measured and result.score < 60.0:
            failing_ids.add(spec.check_id)

    if not failing_ids:
        click.echo("Nothing to scaffold — all templateable checks are passing.")
        return

    created: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for check_id in failing_ids:
        for rel_dest, template_name in _CHECK_TEMPLATES[check_id]:
            dest = path / rel_dest
            if dest.exists() and not force:
                skipped.append(f"  {rel_dest}  (exists; use --force to overwrite)")
                continue
            try:
                text = _load_template(template_name)
                text = _substitute(text, ctx)
            except FileNotFoundError:
                errors.append(f"  {rel_dest}  (template '{template_name}' not found)")
                continue

            if dry_run:
                created.append(f"  {rel_dest}  [dry-run]")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                created.append(f"  {rel_dest}")

    if created:
        action = "Would create" if dry_run else "Created"
        click.echo(f"{action}:")
        for line in created:
            click.echo(line)
    if skipped:
        click.echo("Skipped (already exist):")
        for line in skipped:
            click.echo(line)
    if errors:
        click.echo("Errors:", err=True)
        for line in errors:
            click.echo(line, err=True)
        sys.exit(1)
