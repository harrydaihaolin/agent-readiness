"""Check: git.has_history

A repository with a meaningful commit history gives agents important
context: they can look at diffs to understand why something was done
a certain way, track down regressions, and understand the shape of
the codebase's evolution. A fresh repo (0-1 commits) provides no such
context.
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


@register(
    check_id="git.has_history",
    pillar=Pillar.FLOW,
    title="Repository has a meaningful commit history",
    explanation="""
    A git history with several commits helps agents understand why code
    is structured the way it is. They can use `git log`, `git blame`,
    and `git diff` to investigate bugs, understand design decisions, and
    orient themselves in the codebase. A single-commit or history-less
    repo strips all that context away.
    """,
    weight=1.0,
)
def check_git_has_history(ctx: RepoContext) -> CheckResult:
    # A shallow clone (.git/shallow exists) always reports 1 commit even for
    # repos with thousands. Mark as not_measured so we don't penalise repos
    # that were scanned with `--depth 1` (common in CI pipelines).
    shallow_file = ctx.root / ".git" / "shallow"
    if shallow_file.is_file():
        return CheckResult(
            check_id="git.has_history",
            pillar=Pillar.FLOW,
            score=100.0,
            not_measured=True,
            findings=[Finding(
                check_id="git.has_history",
                pillar=Pillar.FLOW,
                severity=Severity.INFO,
                message=(
                    "Shallow clone detected (.git/shallow) — commit count "
                    "is unreliable. Re-run with a full clone to measure history depth."
                ),
            )],
        )

    count = ctx.commit_count

    if count == 0:
        return CheckResult(
            check_id="git.has_history",
            pillar=Pillar.FLOW,
            score=0.0,
            findings=[Finding(
                check_id="git.has_history",
                pillar=Pillar.FLOW,
                severity=Severity.WARN,
                message="Repository has no commits (not a git repo or empty).",
                fix_hint="Initialise git and commit the initial project state.",
            )],
        )

    if count == 1:
        return CheckResult(
            check_id="git.has_history",
            pillar=Pillar.FLOW,
            score=30.0,
            findings=[Finding(
                check_id="git.has_history",
                pillar=Pillar.FLOW,
                severity=Severity.WARN,
                message="Repository has only 1 commit — very little history for agents to use.",
                fix_hint="Make small, meaningful commits as the project evolves.",
            )],
        )

    if count <= 5:
        return CheckResult(
            check_id="git.has_history",
            pillar=Pillar.FLOW,
            score=70.0,
            findings=[Finding(
                check_id="git.has_history",
                pillar=Pillar.FLOW,
                severity=Severity.INFO,
                message=f"Repository has {count} commits — a start, but more history helps agents.",
            )],
        )

    # 6+ commits
    return CheckResult(
        check_id="git.has_history",
        pillar=Pillar.FLOW,
        score=100.0,
        findings=[Finding(
            check_id="git.has_history",
            pillar=Pillar.FLOW,
            severity=Severity.INFO,
            message=f"Repository has {count} commits.",
        )],
    )
