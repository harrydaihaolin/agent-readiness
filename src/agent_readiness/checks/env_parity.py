"""Check: env.example_parity

When code references environment variables but no .env.example (or
equivalent) file exists, agents have to guess what env vars are needed.
This causes failed runs, hallucinated values, and debugging overhead.
A .env.example makes the required config surface explicit.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


# Patterns indicating env var usage in source code
_ENV_PATTERNS = [
    re.compile(r"\bos\.environ\b"),
    re.compile(r"\bos\.getenv\b"),
    re.compile(r"\bprocess\.env\.\w"),
    re.compile(r"\bENV\["),
    re.compile(r"\bgetenv\s*\("),
    re.compile(r"\bdotenv\b"),
]

_SOURCE_EXTENSIONS = frozenset({".py", ".js", ".ts", ".rb", ".go", ".sh"})

# Directories where env var references are expected and don't require a .env.example.
# Tests commonly use os.environ to inject config for test runs; scripts/ and
# ci/ directories often use env vars for build configuration.
_TEST_DIRS = frozenset({
    "tests", "test", "testing", "specs", "spec", "__tests__",
    "scripts", "script", "tools", "ci", "e2e", "integration",
    "conftest",
})

# Per-extension patterns to strip single-line comments before pattern matching.
# This avoids false positives from commented-out code and documentation.
_COMMENT_LINE_RE: dict[str, re.Pattern[str]] = {
    ".py": re.compile(r"^\s*#.*$", re.MULTILINE),
    ".rb": re.compile(r"^\s*#.*$", re.MULTILINE),
    ".sh": re.compile(r"^\s*#.*$", re.MULTILINE),
    ".js": re.compile(r"^\s*//.*$", re.MULTILINE),
    ".ts": re.compile(r"^\s*//.*$", re.MULTILINE),
    ".go": re.compile(r"^\s*//.*$", re.MULTILINE),
}


def _strip_comments(text: str, suffix: str) -> str:
    """Remove single-line comment lines for the given file extension."""
    pat = _COMMENT_LINE_RE.get(suffix)
    if pat is None:
        return text
    return pat.sub("", text)

_ENV_EXAMPLE_NAMES = (
    ".env.example", ".env.sample", ".env.dist",
    ".env.template", ".env.defaults", ".env.local.example",
    "env.example", "example.env",
)


@register(
    check_id="env.example_parity",
    pillar=Pillar.FLOW,
    title="Environment variables are documented in .env.example",
    explanation="""
    When code reads from environment variables (os.environ, process.env,
    etc.) but no .env.example exists, an agent running the code cold will
    encounter cryptic errors or silent failures from missing config. A
    .env.example file lists every required variable so an agent can
    provision them before the first run.
    """,
    weight=0.9,
)
def check_env_example_parity(ctx: RepoContext) -> CheckResult:
    # Find source files — exclude test and script directories where env var usage
    # is for test config injection, not application configuration that needs documenting.
    source_files = [
        f for f in ctx._files
        if f.suffix in _SOURCE_EXTENSIONS
        and not (len(f.parts) >= 2 and f.parts[0].lower() in _TEST_DIRS)
    ]

    if not source_files:
        return CheckResult(
            check_id="env.example_parity",
            pillar=Pillar.FLOW,
            score=100.0,
            weight=0.9,
            not_measured=True,
            findings=[Finding(
                check_id="env.example_parity",
                pillar=Pillar.FLOW,
                severity=Severity.INFO,
                message="No source files found; env parity check not applicable.",
            )],
        )

    # Scan for env var usage (strip comment lines first to avoid false positives)
    has_env_refs = False
    for f in source_files:
        raw = ctx.read_text(f) or ""
        text = _strip_comments(raw, f.suffix)
        for pat in _ENV_PATTERNS:
            if pat.search(text):
                has_env_refs = True
                break
        if has_env_refs:
            break

    if not has_env_refs:
        return CheckResult(
            check_id="env.example_parity",
            pillar=Pillar.FLOW,
            score=100.0,
            weight=0.9,
            findings=[Finding(
                check_id="env.example_parity",
                pillar=Pillar.FLOW,
                severity=Severity.INFO,
                message="No env var usage detected in source files.",
            )],
        )

    # Env refs found — check for .env.example at root and one level deep
    _SUBDIRS_TO_CHECK = ("", "config", "deploy", "docker", "infra", "env", "envs")
    for subdir in _SUBDIRS_TO_CHECK:
        base = ctx.root / subdir if subdir else ctx.root
        for name in _ENV_EXAMPLE_NAMES:
            candidate = base / name
            if candidate.is_file():
                display = str(Path(subdir) / name) if subdir else name
                return CheckResult(
                    check_id="env.example_parity",
                    pillar=Pillar.FLOW,
                    score=100.0,
                    weight=0.9,
                    findings=[Finding(
                        check_id="env.example_parity",
                        pillar=Pillar.FLOW,
                        severity=Severity.INFO,
                        message=f"Env var usage found and documented in {display}.",
                    )],
                )

    return CheckResult(
        check_id="env.example_parity",
        pillar=Pillar.FLOW,
        score=40.0,
        weight=0.9,
        findings=[Finding(
            check_id="env.example_parity",
            pillar=Pillar.FLOW,
            severity=Severity.WARN,
            message="Env var usage found in source files but no .env.example present.",
            fix_hint="Add .env.example listing all required env vars (with placeholder values).",
        )],
    )
