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
    ("lefthook.toml", "Lefthook", False),
    (".pre-commit-config.yaml", "pre-commit framework", False),
    (".pre-commit-config.yml", "pre-commit framework", False),
    (".claude/settings.json", "Claude Code hooks (PostToolUse)", False),
    # Cursor editor hooks
    (".cursor/settings.json", "Cursor hooks", False),
    # Overcommit (Ruby) and commitlint config
    (".overcommit.yml", "Overcommit", False),
    ("commitlint.config.js", "commitlint", False),
    ("commitlint.config.ts", "commitlint", False),
    (".commitlintrc", "commitlint", False),
    (".commitlintrc.json", "commitlint", False),
    (".commitlintrc.yml", "commitlint", False),
    # simple-git-hooks (lightweight alternative to Husky)
    (".simple-git-hooks.json", "simple-git-hooks", False),
    # lint-staged — often used alongside Husky; config at root signals hooks are wired
    (".lintstagedrc", "lint-staged", False),
    (".lintstagedrc.json", "lint-staged", False),
    (".lintstagedrc.yml", "lint-staged", False),
    ("lint-staged.config.js", "lint-staged", False),
    # Trunk (git hooks + CI integration)
    (".trunk/trunk.yaml", "Trunk", False),
]


def _hooks_in_package_json(ctx: RepoContext) -> str | None:
    """Return a label if package.json declares a hook tool as a dependency."""
    text = ctx.read_text("package.json")
    if text is None:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    dev_deps = data.get("devDependencies") or {}
    deps = data.get("dependencies") or {}
    all_deps = {**dev_deps, **deps}
    # Direct config keys also signal hook setup
    for key in ("husky", "simple-git-hooks", "lint-staged"):
        if key in all_deps or key in data:
            return key.title()
    return None


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
    # Husky v4 uses .husky/ (already above); Husky v6+ and similar tools are
    # declared in package.json devDependencies or as top-level config keys.
    if not found:
        pkg_label = _hooks_in_package_json(ctx)
        if pkg_label:
            found.append(f"{pkg_label} (declared in package.json)")

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
