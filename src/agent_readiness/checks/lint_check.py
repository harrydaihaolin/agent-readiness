"""Check: lint.configured

A linter enforces style, catches common bugs, and (for AI-generated code)
provides a consistent target to aim at. When an agent generates code and
there's no linter, "does this code follow the project's style?" is
unanswerable without reading the entire codebase. With a linter config
the agent can run one command and get a precise list of deviations.
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


_LINT_FILES = (
    # Python
    "ruff.toml", ".ruff.toml",
    ".flake8",
    "pylintrc", ".pylintrc",
    # JavaScript / TypeScript
    ".eslintrc", ".eslintrc.js", ".eslintrc.json",
    ".eslintrc.yml", ".eslintrc.cjs",
    "eslint.config.js", "eslint.config.mjs",
    # Ruby
    ".rubocop.yml",
    # Go
    ".golangci.yml", ".golangci.yaml",
    # PHP
    "phpcs.xml",
    # JS/TS unified toolchain
    "biome.json",
    # Rust — rustfmt and clippy configuration
    "rustfmt.toml", ".rustfmt.toml",
    "clippy.toml", ".clippy.toml",
    # C / C++
    ".clang-format",
    ".clang-tidy",
    # Pre-commit framework — hooks often include linters
    ".pre-commit-config.yaml",
    # Java / Kotlin
    "checkstyle.xml", ".checkstyle",
    # Swift
    ".swiftlint.yml",
)

_PYPROJECT_SECTIONS = ("[tool.ruff]", "[tool.flake8]", "[tool.pylint]")


@register(
    check_id="lint.configured",
    pillar=Pillar.FEEDBACK,
    title="Linter is configured",
    explanation="""
    A configured linter (ruff, eslint, golangci-lint, etc.) lets an agent
    check whether generated code conforms to the project's style in one
    command. Without a linter, the agent must guess style conventions from
    the existing codebase — slow, inconsistent, and fragile.
    """,
    weight=0.9,
)
def check_lint_configured(ctx: RepoContext) -> CheckResult:
    # Check for dedicated config files
    for name in _LINT_FILES:
        if (ctx.root / name).is_file():
            return CheckResult(
                check_id="lint.configured",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                weight=0.9,
                findings=[Finding(
                    check_id="lint.configured",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message=f"Linter config found: {name}",
                )],
            )

    # Check pyproject.toml for linter sections
    pyproject = ctx.read_text("pyproject.toml")
    if pyproject:
        for section in _PYPROJECT_SECTIONS:
            if section in pyproject:
                return CheckResult(
                    check_id="lint.configured",
                    pillar=Pillar.FEEDBACK,
                    score=100.0,
                    weight=0.9,
                    findings=[Finding(
                        check_id="lint.configured",
                        pillar=Pillar.FEEDBACK,
                        severity=Severity.INFO,
                        message=f"Linter configured in pyproject.toml ({section})",
                    )],
                )

    return CheckResult(
        check_id="lint.configured",
        pillar=Pillar.FEEDBACK,
        score=0.0,
        weight=0.9,
        findings=[Finding(
            check_id="lint.configured",
            pillar=Pillar.FEEDBACK,
            severity=Severity.WARN,
            message="No linter configuration found.",
            fix_hint=(
                "Add ruff.toml (Python), .eslintrc.json (JS/TS), or .golangci.yml (Go) "
                "to give agents a consistent style target."
            ),
        )],
    )
