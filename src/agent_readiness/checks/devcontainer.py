"""Check: devcontainer.present

A devcontainer definition provides a reproducible, one-click environment
for any developer (or agent) to spin up. Without it, agents must infer
the correct toolchain, OS, and system deps from indirect signals. With
one, `code --open-in-container .` gives a fully-configured environment
in seconds.

Scoring:
- .devcontainer/devcontainer.json (or .devcontainer.json) found:  100
- Not found:                                                         0
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity

_DEVCONTAINER_PATHS = (
    ".devcontainer/devcontainer.json",
    ".devcontainer.json",
    # Gitpod
    ".gitpod.yml",
    ".gitpod.yaml",
    # Nix shell — reproducible environment even without Docker
    "shell.nix",
    # CodeSandbox
    "sandbox.config.json",
)


@register(
    check_id="devcontainer.present",
    pillar=Pillar.FLOW,
    title="Dev container configuration present",
    explanation="""
    A devcontainer definition (.devcontainer/devcontainer.json) tells
    VS Code and GitHub Codespaces exactly which image, extensions, and
    post-create commands are needed. Agents working in these environments
    get a pre-configured workspace with the right toolchain, eliminating
    "works on my machine" failures and reducing setup friction to zero.
    """,
    weight=0.8,
)
def check(ctx: RepoContext) -> CheckResult:
    for rel in _DEVCONTAINER_PATHS:
        if (ctx.root / rel).is_file():
            return CheckResult(
                check_id="devcontainer.present",
                pillar=Pillar.FLOW,
                score=100.0,
                weight=0.8,
                findings=[Finding(
                    check_id="devcontainer.present",
                    pillar=Pillar.FLOW,
                    severity=Severity.INFO,
                    message=f"Dev container config found: {rel}",
                )],
            )

    # .devcontainer/ directory with any content (docker-compose.yml etc.)
    dc_dir = ctx.root / ".devcontainer"
    if dc_dir.is_dir() and any(dc_dir.iterdir()):
        return CheckResult(
            check_id="devcontainer.present",
            pillar=Pillar.FLOW,
            score=100.0,
            weight=0.8,
            findings=[Finding(
                check_id="devcontainer.present",
                pillar=Pillar.FLOW,
                severity=Severity.INFO,
                message="Dev container config found: .devcontainer/",
            )],
        )

    return CheckResult(
        check_id="devcontainer.present",
        pillar=Pillar.FLOW,
        score=0.0,
        weight=0.8,
        findings=[Finding(
            check_id="devcontainer.present",
            pillar=Pillar.FLOW,
            severity=Severity.WARN,
            message="No devcontainer configuration found.",
            fix_hint=(
                "Add .devcontainer/devcontainer.json to define a reproducible "
                "development environment (image, extensions, post-create commands)."
            ),
        )],
    )
