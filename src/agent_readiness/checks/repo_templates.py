"""Check: templates.present

Issue templates, a PR template, and a CODEOWNERS file reduce the friction
of agent-driven contributions. Without them an agent opening a PR or issue
has no guidance on what information to include, and reviews may be delayed
because no owner is notified automatically.

Scoring (out of 3 items):
- 0 present:  0
- 1 present: 40
- 2 present: 70
- 3 present: 100
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


@register(
    check_id="templates.present",
    pillar=Pillar.FLOW,
    title="Issue/PR templates and CODEOWNERS present",
    explanation="""
    GitHub issue templates, a PR template, and a CODEOWNERS file reduce
    agent-driven contribution friction. Issue templates guide an agent on
    what information to include when filing a bug or feature request.
    The PR template prompts for a description and test plan. CODEOWNERS
    routes review requests automatically so PRs don't languish without
    a reviewer. All three together ensure agent-opened contributions move
    through the process without human hand-holding.
    """,
    weight=0.7,
)
def check(ctx: RepoContext) -> CheckResult:
    present: list[str] = []
    missing: list[str] = []

    # Issue templates
    issue_tmpl_dir = ctx.root / ".github" / "ISSUE_TEMPLATE"
    if issue_tmpl_dir.is_dir() and any(
        f.suffix in (".md", ".yml", ".yaml")
        for f in issue_tmpl_dir.iterdir()
        if f.is_file()
    ):
        present.append("issue templates")
    else:
        missing.append("issue templates (.github/ISSUE_TEMPLATE/)")

    # PR template
    pr_template_paths = (
        ".github/pull_request_template.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "PULL_REQUEST_TEMPLATE.md",
        "pull_request_template.md",
    )
    if any((ctx.root / p).is_file() for p in pr_template_paths):
        present.append("PR template")
    else:
        missing.append("PR template (.github/pull_request_template.md)")

    # CODEOWNERS
    codeowners_paths = (
        "CODEOWNERS",
        ".github/CODEOWNERS",
        "docs/CODEOWNERS",
    )
    if any((ctx.root / p).is_file() for p in codeowners_paths):
        present.append("CODEOWNERS")
    else:
        missing.append("CODEOWNERS")

    score_map = {0: 0.0, 1: 40.0, 2: 70.0, 3: 100.0}
    score = score_map[len(present)]

    findings: list[Finding] = []
    if present:
        findings.append(Finding(
            check_id="templates.present",
            pillar=Pillar.FLOW,
            severity=Severity.INFO,
            message=f"Found: {', '.join(present)}.",
        ))
    for item in missing:
        findings.append(Finding(
            check_id="templates.present",
            pillar=Pillar.FLOW,
            severity=Severity.WARN,
            message=f"Missing: {item}.",
            fix_hint=f"Add {item} to streamline agent-driven contributions.",
        ))

    return CheckResult(
        check_id="templates.present",
        pillar=Pillar.FLOW,
        score=score,
        weight=0.7,
        findings=findings,
    )
