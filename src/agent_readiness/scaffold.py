"""scaffold.py — generate missing agent-readiness files from templates.

Called by ``agent-readiness scaffold [PATH] [--dry-run] [--force] [--only]``.
Fully headless: no interactive prompts. Use ``--dry-run`` to preview.

Post-Q1 the scaffolder is driven by the YAML rules pack: we evaluate
every rule whose id appears in :data:`_CHECK_TEMPLATES`, and write the
mapped templates whenever a rule fires.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import evaluate_rules
from agent_readiness.rules_runtime import load_default_rules


# Maps rule_id -> list of (relative_dest, template_name) tuples.
# Each entry describes one file this check requires.
_CHECK_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    # ``agent_docs.canonical`` is the warn-level rule that fires when
    # AGENTS.md is missing at the root. ``agent_docs.present`` is the
    # softer info-level rule for the broader "any agent-targeted doc"
    # contract. Both map to the same template; whichever fires first
    # gets the scaffold to land.
    "agent_docs.canonical": [
        ("AGENTS.md", "AGENTS.md"),
    ],
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
    "safety.dependency_automation": [
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
        here = Path(__file__).parent
        template_path = here / "templates" / name
        if template_path.is_file():
            return template_path.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Template not found: {name}")


def _substitute(text: str, ctx: RepoContext) -> str:
    """Replace ``{{PLACEHOLDER}}`` tokens in template text with
    repo-specific values.

    The substitution runs the same probe stack as ``context_probe``
    uses for rule-action templates, so the scaffolder's AGENTS.md
    template ships with the *actual* install / test / lint command for
    the detected language instead of a "<replace with your install
    command>" placeholder a human has to fill in. If the probe can't
    resolve (no manifest, no file extensions to count), the templates
    fall back to a generic phrase (``your install command``) so the
    file still reads as English rather than a literal placeholder.
    """
    from agent_readiness.rules_eval.context_probe import run_probes

    probes = [
        {"detect": "primary_language"},
        {"detect": "primary_manifest"},
        {"detect": "package_manager"},
    ]
    vars = run_probes(probes, ctx)

    repo_name = ctx.root.name
    primary_language = vars.get("primary_language") or "your project's primary language"
    install_cmd = vars.get("language_install_command") or "your install command"
    test_cmd = vars.get("language_test_command") or "your test command"
    lint_cmd = vars.get("language_lint_command") or "your lint command"

    return (
        text
        .replace("{{REPO_NAME}}", repo_name)
        .replace("{{PROJECT_NAME}}", repo_name)
        .replace("{{PRIMARY_LANGUAGE}}", primary_language)
        .replace("{{INSTALL_COMMAND}}", install_cmd)
        .replace("{{TEST_COMMAND}}", test_cmd)
        .replace("{{LINT_COMMAND}}", lint_cmd)
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

    ctx = RepoContext(root=path)
    rules = load_default_rules()

    filter_ids: set[str] | None = None
    if only_checks:
        filter_ids = {t.strip() for t in only_checks.split(",")}

    candidate_rules = [
        r for r in rules
        if r.rule_id in _CHECK_TEMPLATES
        and (filter_ids is None or r.rule_id in filter_ids)
    ]

    failing_ids: set[str] = set()
    for result in evaluate_rules(candidate_rules, ctx):
        if not result.not_measured and result.score < 60.0:
            failing_ids.add(result.check_id)

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
