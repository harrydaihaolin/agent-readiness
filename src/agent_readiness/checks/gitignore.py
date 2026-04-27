"""Check: gitignore.covers_junk

A .gitignore that covers generated files (__pycache__, node_modules,
.env, dist/) prevents agents from accidentally staging and committing
build artifacts, secrets, or vendored code. Without a .gitignore, an
agent doing `git add -A` will stage everything — a security and
correctness risk.
"""

from __future__ import annotations

import re

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


# Pattern groups that a .gitignore should cover.
# Each group is (description, list of regexes — any match satisfies the group).
_PATTERN_GROUPS = [
    (
        "compiled Python (*.pyc / __pycache__)",
        [re.compile(r"__pycache__"), re.compile(r"\*\.pyc")],
    ),
    (
        "node_modules",
        [re.compile(r"node_modules")],
    ),
    (
        ".env files",
        [re.compile(r"\.env\b")],
    ),
    (
        "build output (dist/ or build/)",
        [re.compile(r"^/?dist/", re.M), re.compile(r"^/?build/", re.M)],
    ),
]


def _covered_groups(gitignore_text: str) -> int:
    count = 0
    for _desc, patterns in _PATTERN_GROUPS:
        for pat in patterns:
            if pat.search(gitignore_text):
                count += 1
                break
    return count


@register(
    check_id="gitignore.covers_junk",
    pillar=Pillar.SAFETY,
    title=".gitignore covers build artifacts and secrets",
    explanation="""
    A .gitignore that misses __pycache__, node_modules, .env, or dist/
    exposes the repo to accidental commits of compiled code, vendored
    dependencies, or secrets. For an agent doing `git add -A` this is
    especially dangerous: it will happily stage everything the .gitignore
    doesn't cover. Safety check — a bad .gitignore applies the soft cap.
    """,
    weight=1.0,
)
def check_gitignore_covers_junk(ctx: RepoContext) -> CheckResult:
    gitignore_path = ctx.root / ".gitignore"
    if not gitignore_path.is_file():
        return CheckResult(
            check_id="gitignore.covers_junk",
            pillar=Pillar.SAFETY,
            score=0.0,
            findings=[Finding(
                check_id="gitignore.covers_junk",
                pillar=Pillar.SAFETY,
                severity=Severity.WARN,
                message="No .gitignore found.",
                fix_hint=(
                    "Add .gitignore covering at minimum: __pycache__, .env, "
                    "node_modules, dist/, build/."
                ),
            )],
        )

    text = gitignore_path.read_text(encoding="utf-8", errors="replace")
    covered = _covered_groups(text)

    if covered == 4:
        score = 100.0
    elif covered >= 2:
        score = 70.0
    elif covered == 1:
        score = 30.0
    else:
        score = 0.0

    findings: list[Finding] = []
    if score < 70.0:
        missing_groups = []
        for desc, patterns in _PATTERN_GROUPS:
            if not any(pat.search(text) for pat in patterns):
                missing_groups.append(desc)
        findings.append(Finding(
            check_id="gitignore.covers_junk",
            pillar=Pillar.SAFETY,
            severity=Severity.WARN,
            message=f".gitignore is missing patterns for: {', '.join(missing_groups)}.",
            fix_hint="Add the missing patterns to .gitignore to prevent accidental commits.",
        ))

    return CheckResult(
        check_id="gitignore.covers_junk",
        pillar=Pillar.SAFETY,
        score=score,
        findings=findings,
    )
