"""Check: hooks.configured

Git hooks (Husky, Lefthook, pre-commit) provide immediate pre-commit
or pre-push feedback. Claude Code hooks (.claude/settings.json) configure
agent-specific behaviors like PostToolUse guardrails. Either type gives
agents faster, localised feedback before changes leave the local env.

Scoring:
- Any hook framework detected:  100
- None found:                     0
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity

# (path_relative_to_root, human label, is_dir)
_HOOK_SIGNALS: list[tuple[str, str, bool]] = [
    (".husky", "Husky git hooks", True),
    ("lefthook.yml", "Lefthook", False),
    (".lefthook.yml", "Lefthook", False),
    (".pre-commit-config.yaml", "pre-commit framework", False),
    (".claude/settings.json", "Claude Code hooks (PostToolUse)", False),
]


@register(
    check_id="hooks.configured",
    pillar=Pillar.FEEDBACK,
    title="Git or agent hooks configured",
    explanation="""
    Git hooks (Husky, Lefthook, pre-commit) run linters, tests, or formatters
    automatically before a commit or push. This gives an agent sub-second
    feedback without needing to invoke CI. Claude Code hooks
    (.claude/settings.json PostToolUse) add a second layer: they fire after
    every tool call and can enforce repo-specific rules. Even one hook
    framework signals that the repo was designed for high-frequency,
    automated iteration — which is exactly what coding agents do.
    """,
    weight=0.7,
)
def check(ctx: RepoContext) -> CheckResult:
    found: list[str] = []
    for rel, label, is_dir in _HOOK_SIGNALS:
        target = ctx.root / rel
        if (is_dir and target.is_dir()) or (not is_dir and target.is_file()):
            found.append(label)

    if found:
        return CheckResult(
            check_id="hooks.configured",
            pillar=Pillar.FEEDBACK,
            score=100.0,
            weight=0.7,
            findings=[Finding(
                check_id="hooks.configured",
                pillar=Pillar.FEEDBACK,
                severity=Severity.INFO,
                message=f"Hooks configured: {', '.join(found)}.",
            )],
        )

    return CheckResult(
        check_id="hooks.configured",
        pillar=Pillar.FEEDBACK,
        score=0.0,
        weight=0.7,
        findings=[Finding(
            check_id="hooks.configured",
            pillar=Pillar.FEEDBACK,
            severity=Severity.WARN,
            message="No git or agent hooks configured.",
            fix_hint=(
                "Add .pre-commit-config.yaml (pre-commit framework) or "
                ".husky/ (Husky) to run checks before commits. "
                "Add .claude/settings.json to configure Claude Code hooks."
            ),
        )],
    )
