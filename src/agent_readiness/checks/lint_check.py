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
    "eslint.config.js", "eslint.config.mjs", "eslint.config.ts",
    # JavaScript / TypeScript — Prettier formatter
    ".prettierrc", ".prettierrc.json", ".prettierrc.js",
    ".prettierrc.yml", ".prettierrc.yaml", ".prettierrc.toml",
    ".prettierrc.cjs", "prettier.config.js", "prettier.config.cjs",
    # Ruby
    ".rubocop.yml",
    # Go
    ".golangci.yml", ".golangci.yaml",
    # PHP
    "phpcs.xml",
    # JS/TS unified toolchain (Biome — replaces ESLint + Prettier)
    "biome.json", "biome.jsonc",
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
    # Kotlin — detekt static analysis
    "detekt.yml", "detekt.yaml",
    # Swift
    ".swiftlint.yml",
    # Dockerfile linting (Hadolint)
    ".hadolint.yml", ".hadolint.yaml",
    # Editor-level formatting (often the only lint signal in simple projects)
    ".editorconfig",
)

_PYPROJECT_SECTIONS = ("[tool.ruff]", "[tool.flake8]", "[tool.pylint]", "[tool.black]")


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
    import json as _json

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

    # setup.cfg [flake8] or [pylint] section
    setup_cfg = ctx.read_text("setup.cfg")
    if setup_cfg and ("[flake8]" in setup_cfg or "[pylint]" in setup_cfg):
        section = "[flake8]" if "[flake8]" in setup_cfg else "[pylint]"
        return CheckResult(
            check_id="lint.configured",
            pillar=Pillar.FEEDBACK,
            score=100.0,
            weight=0.9,
            findings=[Finding(
                check_id="lint.configured",
                pillar=Pillar.FEEDBACK,
                severity=Severity.INFO,
                message=f"Linter configured in setup.cfg ({section})",
            )],
        )

    # ESLint or Prettier config embedded in package.json
    pkg_text = ctx.read_text("package.json")
    if pkg_text:
        try:
            pkg = _json.loads(pkg_text)
            for key in ("eslintConfig", "prettier", "lint-staged"):
                if key in pkg:
                    return CheckResult(
                        check_id="lint.configured",
                        pillar=Pillar.FEEDBACK,
                        score=100.0,
                        weight=0.9,
                        findings=[Finding(
                            check_id="lint.configured",
                            pillar=Pillar.FEEDBACK,
                            severity=Severity.INFO,
                            message=f'Linter configured in package.json ("{key}" key)',
                        )],
                    )
        except (_json.JSONDecodeError, TypeError):
            pass

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
