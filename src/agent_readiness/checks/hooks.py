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

import json

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity

# (path_relative_to_root, human label, is_dir)
_HOOK_SIGNALS: list[tuple[str, str, bool]] = [
    (".husky", "Husky git hooks", True),
    ("lefthook.yml", "Lefthook", False),
    (".lefthook.yml", "Lefthook", False),
    ("lefthook.yaml", "Lefthook", False),
    (".pre-commit-config.yaml", "pre-commit framework", False),
    (".claude/settings.json", "Claude Code hooks (PostToolUse)", False),
    # Overcommit (Ruby) and commitlint config
    (".overcommit.yml", "Overcommit", False),
    ("commitlint.config.js", "commitlint", False),
    (".commitlintrc", "commitlint", False),
    (".commitlintrc.json", "commitlint", False),
    (".commitlintrc.yml", "commitlint", False),
]


def _husky_in_package_json(ctx: RepoContext) -> bool:
    """Return True if package.json declares husky as a dependency."""
    text = ctx.read_text("package.json")
    if text is None:
        return False
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    dev_deps = data.get("devDependencies") or {}
    deps = data.get("dependencies") or {}
    return "husky" in dev_deps or "husky" in deps


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
    # Husky v4 uses .husky/ (already above); Husky v6+ is declared in
    # package.json devDependencies without a .husky/ directory necessarily
    # existing until `husky install` is run.
    if not found and _husky_in_package_json(ctx):
        found.append("Husky (declared in package.json)")

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
