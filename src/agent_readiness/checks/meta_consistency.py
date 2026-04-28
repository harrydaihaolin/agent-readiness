"""Check: meta.consistency

Detects contradictions between what the README documents and what the
repository actually contains. These inconsistencies confuse agents:
the agent reads the README expecting tool X to be present, then fails
to find it, wastes turns debugging, and may hallucinate a workaround.

All signals are re-derived from RepoContext to keep checks stateless.
"""

from __future__ import annotations

import re

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


# README sections to search — look for the file by common names
_README_NAMES = ("README.md", "README.rst", "README.txt", "README")

# (signal_name, readme_pattern, missing_file_check)
# Each entry: if readme matches the pattern but the file predicate fails → WARN
_CONSISTENCY_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "pytest",
        re.compile(r"\bpytest\b", re.IGNORECASE),
        "pyproject.toml",          # simplest proxy: pytest section lives here or pytest.ini
    ),
    (
        "npm test",
        re.compile(r"\bnpm\s+test\b|\bnpm\s+run\s+test\b", re.IGNORECASE),
        "package.json",
    ),
]

# Agent docs that should not be placeholder-sized (< 100 bytes is suspicious)
_AGENT_DOC_NAMES = ("AGENTS.md", "CLAUDE.md")
_PLACEHOLDER_THRESHOLD = 100  # bytes


def _read_readme(ctx: RepoContext) -> str | None:
    for name in _README_NAMES:
        text = ctx.read_text(name)
        if text is not None:
            return text
    return None


def _has_pytest_config(ctx: RepoContext) -> bool:
    """Return True if any standard pytest config marker is present."""
    if (ctx.root / "pytest.ini").is_file():
        return True
    if (ctx.root / "setup.cfg").is_file():
        txt = ctx.read_text("setup.cfg") or ""
        if "[tool:pytest]" in txt:
            return True
    if (ctx.root / "pyproject.toml").is_file():
        txt = ctx.read_text("pyproject.toml") or ""
        if "[tool.pytest" in txt:
            return True
    return False


@register(
    check_id="meta.consistency",
    pillar=Pillar.COGNITIVE_LOAD,
    title="README claims match repo contents",
    explanation="""
    An agent reads the README to understand how to build, test, and run the
    project. When the README references a tool or command that isn't backed
    by the corresponding config (e.g., "run pytest" but no pyproject.toml
    pytest config), the agent wastes turns debugging or hallucinating fixes.

    This check detects common contradictions:
    - README mentions pytest but no pytest configuration is present.
    - README mentions npm test but no package.json exists.
    - AGENTS.md or CLAUDE.md is present but appears to be a placeholder
      (under 100 bytes).
    """,
    weight=0.5,
)
def check_meta_consistency(ctx: RepoContext) -> CheckResult:
    findings: list[Finding] = []
    readme_text = _read_readme(ctx)

    if readme_text is not None:
        # pytest claim without config
        if _CONSISTENCY_RULES[0][1].search(readme_text) and not _has_pytest_config(ctx):
            findings.append(Finding(
                check_id="meta.consistency",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.WARN,
                message="README references pytest but no pytest configuration was found.",
                fix_hint=(
                    "Add [tool.pytest.ini_options] to pyproject.toml or create "
                    "pytest.ini so agents can discover and run tests."
                ),
            ))

        # npm test claim without package.json
        if _CONSISTENCY_RULES[1][1].search(readme_text) and not (ctx.root / "package.json").is_file():
            findings.append(Finding(
                check_id="meta.consistency",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.WARN,
                message="README references npm test but no package.json was found.",
                fix_hint="Add package.json with a test script, or update the README.",
            ))

    # Placeholder agent docs
    for doc_name in _AGENT_DOC_NAMES:
        doc_path = ctx.root / doc_name
        if doc_path.is_file():
            try:
                size = doc_path.stat().st_size
            except OSError:
                continue
            if size < _PLACEHOLDER_THRESHOLD:
                findings.append(Finding(
                    check_id="meta.consistency",
                    pillar=Pillar.COGNITIVE_LOAD,
                    severity=Severity.WARN,
                    message=f"{doc_name} is present but appears to be a placeholder ({size} bytes).",
                    fix_hint=f"Expand {doc_name} with canonical commands, key files, and agent conventions.",
                ))

    if not findings:
        return CheckResult(
            check_id="meta.consistency",
            pillar=Pillar.COGNITIVE_LOAD,
            score=100.0,
            weight=0.5,
            findings=[Finding(
                check_id="meta.consistency",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.INFO,
                message="No consistency issues detected.",
            )],
        )

    # Each finding docks 20 points; floor at 0
    score = max(0.0, 100.0 - len(findings) * 20.0)
    return CheckResult(
        check_id="meta.consistency",
        pillar=Pillar.COGNITIVE_LOAD,
        score=score,
        weight=0.5,
        findings=findings,
    )
