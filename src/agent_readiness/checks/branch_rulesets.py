"""Check: branch_rulesets.configured

GitHub branch rulesets (formerly branch protection rules) enforce review
requirements, status checks, and merge policies. Without them an agent
could push directly to main, bypass required reviews, or merge a PR that
failed CI. The check shells out to `gh` — it returns not_measured if `gh`
is unavailable or not authenticated.

Scoring:
- At least one ruleset configured:  100
- No rulesets found:                  0
- gh unavailable / not authed:   not_measured
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


def _get_remote_owner_repo(ctx: RepoContext) -> tuple[str, str] | None:
    """Parse owner/repo from the git remote URL. Returns None on failure."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=ctx.root, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    # HTTPS: https://github.com/owner/repo.git
    https_match = re.search(r"github\.com[/:]([^/]+)/([^/\s]+?)(?:\.git)?$", url)
    if https_match:
        return https_match.group(1), https_match.group(2)
    return None


@register(
    check_id="branch_rulesets.configured",
    pillar=Pillar.SAFETY,
    title="GitHub branch rulesets configured",
    explanation="""
    GitHub branch rulesets (Settings → Rules → Rulesets) enforce required
    reviewers, passing status checks, and linear history before merges.
    Without them an agent with push access can bypass CI, skip reviews,
    and push broken code directly to the default branch. This check calls
    `gh api repos/{owner}/{repo}/rulesets` — it is marked not_measured when
    the gh CLI is absent or not authenticated.
    """,
    weight=0.8,
)
def check(ctx: RepoContext) -> CheckResult:
    _not_measured = CheckResult(
        check_id="branch_rulesets.configured",
        pillar=Pillar.SAFETY,
        score=0.0,
        weight=0.8,
        not_measured=True,
        findings=[Finding(
            check_id="branch_rulesets.configured",
            pillar=Pillar.SAFETY,
            severity=Severity.INFO,
            message=(
                "Branch ruleset check skipped: requires the gh CLI with "
                "a GitHub remote and valid authentication."
            ),
        )],
    )

    # Require gh CLI
    if shutil.which("gh") is None:
        return _not_measured

    # Require a GitHub remote
    if not ctx.is_git_repo:
        return _not_measured
    owner_repo = _get_remote_owner_repo(ctx)
    if owner_repo is None:
        return _not_measured
    owner, repo = owner_repo

    # Require gh auth
    auth_check = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True, text=True, check=False,
    )
    if auth_check.returncode != 0:
        return _not_measured

    # Query rulesets
    result = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/rulesets"],
        capture_output=True, text=True, check=False,
        timeout=15,
    )
    if result.returncode != 0:
        return _not_measured

    try:
        rulesets = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return _not_measured

    if not isinstance(rulesets, list) or len(rulesets) == 0:
        return CheckResult(
            check_id="branch_rulesets.configured",
            pillar=Pillar.SAFETY,
            score=0.0,
            weight=0.8,
            findings=[Finding(
                check_id="branch_rulesets.configured",
                pillar=Pillar.SAFETY,
                severity=Severity.INFO,
                message=f"No branch rulesets configured for {owner}/{repo}.",
                fix_hint=(
                    "Add a branch ruleset under Settings → Rules → Rulesets "
                    "to require passing CI and code review before merging."
                ),
            )],
        )

    names = [r.get("name", "unnamed") for r in rulesets if isinstance(r, dict)]
    return CheckResult(
        check_id="branch_rulesets.configured",
        pillar=Pillar.SAFETY,
        score=100.0,
        weight=0.8,
        findings=[Finding(
            check_id="branch_rulesets.configured",
            pillar=Pillar.SAFETY,
            severity=Severity.INFO,
            message=f"Branch rulesets found: {', '.join(names)}.",
        )],
    )
