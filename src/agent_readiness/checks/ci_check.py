"""Check: ci.configured

Continuous integration is the canonical feedback loop: every push or PR
triggers the test suite, static analysis, and build. Without CI an agent
can't verify whether its changes pass. With CI the agent gets deterministic
"did this work?" feedback after every push.

Detection is intentionally a flat allow-list of well-known config files
and directories. We accept both "trigger" configs (GitHub Actions,
CircleCI, Jenkins, …) and portable build-recipe configs (Earthly, Drone,
Woodpecker) because in monorepos the trigger often lives outside the
tracked repo (Buildkite/Jenkins/internal orchestrator) while the
recipe lives in-tree. Either signal is enough to know "automated CI
exists" — the rubric question this check answers.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


def _has_yaml_in_dir(p: Path) -> bool:
    if not p.is_dir():
        return False
    return any(c.is_file() and c.suffix in (".yml", ".yaml") for c in p.iterdir())


# (label, predicate). First match wins. Order is "trigger configs first,
# portable build recipes last" so the message names the most specific
# thing we found.
_DETECTORS: tuple[tuple[str, Callable[[Path], bool]], ...] = (
    ("GitHub Actions",      lambda r: _has_yaml_in_dir(r / ".github" / "workflows")),
    ("CircleCI",            lambda r: (r / ".circleci" / "config.yml").is_file()),
    ("Buildkite",           lambda r: (r / ".buildkite" / "pipeline.yml").is_file()),
    ("Travis CI",           lambda r: (r / ".travis.yml").is_file()),
    ("Jenkins",             lambda r: (r / "Jenkinsfile").is_file()),
    ("GitLab CI",           lambda r: (r / ".gitlab-ci.yml").is_file()),
    ("Azure Pipelines",     lambda r: (r / "azure-pipelines.yml").is_file()),
    ("Bitbucket Pipelines", lambda r: (r / "bitbucket-pipelines.yml").is_file()),
    ("AppVeyor",            lambda r: (r / "appveyor.yml").is_file()),
    ("Drone CI", lambda r: (r / ".drone.yml").is_file()
                           or (r / ".drone.yaml").is_file()),
    ("Woodpecker CI", lambda r: (r / ".woodpecker.yml").is_file()
                                or (r / ".woodpecker.yaml").is_file()
                                or _has_yaml_in_dir(r / ".woodpecker")),
    ("Earthly", lambda r: (r / "Earthfile").is_file()),
)


@register(
    check_id="ci.configured",
    pillar=Pillar.FEEDBACK,
    title="CI pipeline configured",
    explanation="""
    A CI pipeline (GitHub Actions, CircleCI, GitLab CI, Earthly, etc.)
    provides automated, deterministic feedback after every push. This is
    the fastest possible feedback loop for agents: commit → CI runs →
    pass/fail. Without CI the agent has to run tests locally and parse
    output manually, which is slower and error-prone.

    Detected: GitHub Actions, CircleCI, Buildkite, Travis CI, Jenkins,
    GitLab CI, Azure Pipelines, Bitbucket Pipelines, AppVeyor, Drone CI,
    Woodpecker CI, Earthly. Detection is filename-based; absence here
    does not mean CI doesn't exist (orgs run repos via custom
    orchestrators), it means an agent walking the repo cannot find it.
    """,
    weight=0.9,
)
def check_ci_configured(ctx: RepoContext) -> CheckResult:
    for label, predicate in _DETECTORS:
        if predicate(ctx.root):
            return CheckResult(
                check_id="ci.configured",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                weight=0.9,
                findings=[Finding(
                    check_id="ci.configured",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message=f"CI configuration detected: {label}.",
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
                "Add .github/workflows/ci.yml, an Earthfile, or any other "
                "recognised CI config so agents can find your pipeline."
            ),
        )],
    )
