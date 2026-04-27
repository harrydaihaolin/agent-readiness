"""Check: ci.configured

Continuous integration is the canonical feedback loop: every push or PR
triggers the test suite, static analysis, and build. Without CI an agent
can't verify whether its changes pass. With CI the agent gets deterministic
"did this work?" feedback after every push.
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


# Files / directories indicating CI configuration
_CI_FILES = (
    ".travis.yml",
    "Jenkinsfile",
    ".gitlab-ci.yml",
    "azure-pipelines.yml",
    "bitbucket-pipelines.yml",
    "appveyor.yml",
)

_CI_BUILDKITE = ".buildkite/pipeline.yml"
_CI_CIRCLECI = ".circleci/config.yml"
_CI_GITHUB_WORKFLOWS = ".github/workflows"


@register(
    check_id="ci.configured",
    pillar=Pillar.FEEDBACK,
    title="CI pipeline configured",
    explanation="""
    A CI pipeline (GitHub Actions, CircleCI, GitLab CI, etc.) provides
    automated, deterministic feedback after every push. This is the fastest
    possible feedback loop for agents: commit → CI runs → pass/fail. Without
    CI the agent has to run tests locally and parse output manually, which
    is slower and error-prone.
    """,
    weight=0.9,
)
def check_ci_configured(ctx: RepoContext) -> CheckResult:
    # Check .github/workflows/ for any .yml file
    gha_dir = ctx.root / _CI_GITHUB_WORKFLOWS
    if gha_dir.is_dir():
        has_workflow = any(True for p in gha_dir.iterdir()
                          if p.is_file() and p.suffix in (".yml", ".yaml"))
        if has_workflow:
            return CheckResult(
                check_id="ci.configured",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                weight=0.9,
                findings=[Finding(
                    check_id="ci.configured",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message="GitHub Actions workflows found.",
                )],
            )

    # Check CircleCI
    if (ctx.root / _CI_CIRCLECI).is_file():
        return CheckResult(
            check_id="ci.configured",
            pillar=Pillar.FEEDBACK,
            score=100.0,
            weight=0.9,
            findings=[Finding(
                check_id="ci.configured",
                pillar=Pillar.FEEDBACK,
                severity=Severity.INFO,
                message="CircleCI config found.",
            )],
        )

    # Check Buildkite
    if (ctx.root / _CI_BUILDKITE).is_file():
        return CheckResult(
            check_id="ci.configured",
            pillar=Pillar.FEEDBACK,
            score=100.0,
            weight=0.9,
            findings=[Finding(
                check_id="ci.configured",
                pillar=Pillar.FEEDBACK,
                severity=Severity.INFO,
                message="Buildkite pipeline found.",
            )],
        )

    # Check flat CI files
    for name in _CI_FILES:
        if (ctx.root / name).is_file():
            return CheckResult(
                check_id="ci.configured",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                weight=0.9,
                findings=[Finding(
                    check_id="ci.configured",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message=f"CI config found: {name}",
                )],
            )

    return CheckResult(
        check_id="ci.configured",
        pillar=Pillar.FEEDBACK,
        score=0.0,
        weight=0.9,
        findings=[Finding(
            check_id="ci.configured",
            pillar=Pillar.FEEDBACK,
            severity=Severity.WARN,
            message="No CI configuration found.",
            fix_hint=(
                "Add .github/workflows/ci.yml (or equivalent) to run tests "
                "automatically on every push."
            ),
        )],
    )
