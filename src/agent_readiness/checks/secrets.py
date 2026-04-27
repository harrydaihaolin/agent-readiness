"""Check: secrets.basic_scan

A secret in the tracked tree is a hard problem regardless of what else
is good about the repo: agents that operate in this repo will have it
in their context window, and any commit they make may surface it.

We are deliberately *very* conservative. False positives here are
catastrophic for trust — they cap a user's overall score on noise.
We use specific, high-confidence patterns and skip generic
"high-entropy string" detection in v0.1.

Scoring:
- Any high-confidence match found:    0  (with ERROR-severity findings)
- Clean:                            100

The Safety pillar caps overall score on ERROR findings (RUBRIC.md), so
this check is what triggers the cap when it fires. We skip files that
are clearly examples (.example, .sample, .template suffixes / paths).
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


# High-confidence patterns. Each is conservative enough that a hit is
# very unlikely to be a false positive. Sources: AWS docs format,
# GitHub PAT format, PEM headers.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key id",     re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("AWS secret access key", re.compile(r"(?i)aws_secret_access_key\s*=\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?")),
    ("GitHub PAT (classic)",  re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("GitHub fine-grained PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b")),
    ("Slack token",           re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,72}\b")),
    ("Google API key",        re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Stripe live key",       re.compile(r"\bsk_live_[0-9a-zA-Z]{24,}\b")),
    ("Private key PEM",       re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----")),
]

# Files/paths that are obviously examples; skip them.
_EXAMPLE_HINTS = ("example", "sample", "template", "fixture", "fixtures",
                  "test", "tests", "__tests__", "spec", "specs",
                  ".env.example", ".env.sample", ".env.template")

# Skip very large or clearly-binary files.
_TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".rs",
    ".java", ".kt", ".cs", ".php", ".swift", ".m", ".mm",
    ".sh", ".bash", ".zsh", ".fish",
    ".md", ".rst", ".txt", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".env", ".dotenv", ".conf",
    ".json", ".xml", ".html", ".htm",
}
# We also scan extensionless dotfiles (".env", ".envrc", "Dockerfile", ...).
_NO_EXT_NAMES = {".env", ".envrc", "Dockerfile", "Procfile", "Makefile"}


def _is_example_path(rel: Path) -> bool:
    parts_lower = [p.lower() for p in rel.parts]
    return any(hint in p for hint in _EXAMPLE_HINTS for p in parts_lower)


def _is_scannable(rel: Path) -> bool:
    if rel.suffix.lower() in _TEXT_SUFFIXES:
        return True
    if rel.suffix == "" and rel.name in _NO_EXT_NAMES:
        return True
    return False


@register(
    check_id="secrets.basic_scan",
    pillar=Pillar.SAFETY,
    title="No high-confidence secrets in tracked files",
    explanation="""
    Looks for high-confidence secret patterns: AWS access keys,
    GitHub PATs, Slack tokens, Stripe live keys, Google API keys,
    PEM private-key headers. Deliberately conservative — false positives
    here cap the overall score, so we'd rather miss a borderline case.
    Files under example / sample / fixture / test paths are skipped.
    For broader coverage, layer on a dedicated tool (gitleaks,
    trufflehog) — we don't try to be them.
    """,
)
def check(ctx: RepoContext) -> CheckResult:
    findings: list[Finding] = []
    for rel in ctx.files:
        if _is_example_path(rel) or not _is_scannable(rel):
            continue
        text = ctx.read_text(rel, max_bytes=64_000)
        if text is None:
            continue
        for label, pattern in _PATTERNS:
            m = pattern.search(text)
            if m is None:
                continue
            # Find the line for the match so the finding is actionable.
            line = text.count("\n", 0, m.start()) + 1
            findings.append(Finding(
                check_id="secrets.basic_scan",
                pillar=Pillar.SAFETY,
                severity=Severity.ERROR,
                file=rel,
                line=line,
                message=f"Possible {label} found.",
                fix_hint=("Rotate the secret immediately, remove it from the "
                          "tracked file (rewrite history if needed), and store "
                          "it via env var or secrets manager."),
            ))
            break  # one finding per file is enough to make the point

    score = 0.0 if findings else 100.0
    return CheckResult(
        check_id="secrets.basic_scan",
        pillar=Pillar.SAFETY,
        score=score,
        findings=findings,
    )
