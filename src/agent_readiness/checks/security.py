"""Checks: security.dependabot_configured and security.policy_present

Dependabot automates dependency vulnerability patching — it opens PRs when
new CVEs are published against pinned versions. SECURITY.md documents the
responsible disclosure policy, which agents need to know when they encounter
a potential vulnerability in the course of their work.

Both checks emit WARN severity (not ERROR), so they influence the safety
pillar score without triggering the hard 30-point cap reserved for actual
secrets in tracked files.
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity

_DEPENDABOT_PATHS = (
    ".github/dependabot.yml",
    ".github/dependabot.yaml",
)

_SECURITY_PATHS = (
    "SECURITY.md",
    ".github/SECURITY.md",
    "docs/SECURITY.md",
)


@register(
    check_id="security.dependabot_configured",
    pillar=Pillar.SAFETY,
    title="Dependabot or Renovate configured for dependency updates",
    explanation="""
    Dependabot (and Renovate) automatically open pull requests when
    dependencies have known CVEs or newer versions. Agents that add or
    update dependencies rely on this safety net — without it, a
    transitive vulnerability introduced by an agent-opened PR may go
    unnoticed for weeks. The configuration lives at .github/dependabot.yml.
    """,
    weight=0.8,
)
def check_dependabot(ctx: RepoContext) -> CheckResult:
    # Also accept Renovate as an equivalent tool.
    # Renovate config can live at root or inside .github/.
    renovate_paths = (
        "renovate.json", "renovate.json5",
        ".renovaterc", ".renovaterc.json",
        ".github/renovate.json", ".github/renovate.json5",
        ".gitlab/renovate.json",
    )

    for rel in _DEPENDABOT_PATHS:
        if (ctx.root / rel).is_file():
            return CheckResult(
                check_id="security.dependabot_configured",
                pillar=Pillar.SAFETY,
                score=100.0,
                weight=0.8,
                findings=[Finding(
                    check_id="security.dependabot_configured",
                    pillar=Pillar.SAFETY,
                    severity=Severity.INFO,
                    message=f"Dependabot config found: {rel}",
                )],
            )
    for rel in renovate_paths:
        if (ctx.root / rel).is_file():
            return CheckResult(
                check_id="security.dependabot_configured",
                pillar=Pillar.SAFETY,
                score=100.0,
                weight=0.8,
                findings=[Finding(
                    check_id="security.dependabot_configured",
                    pillar=Pillar.SAFETY,
                    severity=Severity.INFO,
                    message=f"Renovate config found: {rel}",
                )],
            )

    # Snyk — security-focused alternative to Dependabot
    if (ctx.root / ".snyk").is_file():
        return CheckResult(
            check_id="security.dependabot_configured",
            pillar=Pillar.SAFETY,
            score=100.0,
            weight=0.8,
            findings=[Finding(
                check_id="security.dependabot_configured",
                pillar=Pillar.SAFETY,
                severity=Severity.INFO,
                message="Snyk config found: .snyk",
            )],
        )

    return CheckResult(
        check_id="security.dependabot_configured",
        pillar=Pillar.SAFETY,
        score=0.0,
        weight=0.8,
        findings=[Finding(
            check_id="security.dependabot_configured",
            pillar=Pillar.SAFETY,
            severity=Severity.WARN,
            message="No automated dependency update tool configured (Dependabot or Renovate).",
            fix_hint=(
                "Add .github/dependabot.yml to enable automatic dependency "
                "security PRs from GitHub."
            ),
        )],
    )


@register(
    check_id="security.policy_present",
    pillar=Pillar.SAFETY,
    title="Security policy (SECURITY.md) present",
    explanation="""
    SECURITY.md documents how to report vulnerabilities responsibly. When
    an agent encounters a potential security issue in the code it's working
    on, this file tells it the correct escalation path — whether to open a
    public issue, email a security address, or use GitHub's private
    vulnerability reporting. Without it, an agent has no guidance and may
    inadvertently disclose a vulnerability publicly.
    """,
    weight=0.6,
)
def check_security_policy(ctx: RepoContext) -> CheckResult:
    for rel in _SECURITY_PATHS:
        if (ctx.root / rel).is_file():
            return CheckResult(
                check_id="security.policy_present",
                pillar=Pillar.SAFETY,
                score=100.0,
                weight=0.6,
                findings=[Finding(
                    check_id="security.policy_present",
                    pillar=Pillar.SAFETY,
                    severity=Severity.INFO,
                    message=f"Security policy found: {rel}",
                )],
            )

    return CheckResult(
        check_id="security.policy_present",
        pillar=Pillar.SAFETY,
        score=0.0,
        weight=0.6,
        findings=[Finding(
            check_id="security.policy_present",
            pillar=Pillar.SAFETY,
            severity=Severity.WARN,
            message="No SECURITY.md found.",
            fix_hint=(
                "Add SECURITY.md documenting how to report vulnerabilities "
                "(contact email, GitHub private reporting, embargo policy)."
            ),
        )],
    )
