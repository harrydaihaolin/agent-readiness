"""Check: agent_docs.present

A repo that explicitly speaks to AI agents — via AGENTS.md, CLAUDE.md,
.cursorrules, or .github/copilot-instructions.md — is meaningfully more
ready than one that doesn't. These files communicate conventions
(branch naming, code style, commit message format, do-not-touch dirs)
that an agent would otherwise have to infer from observation.

Scoring:
- No agent-targeted docs:           0
- One present:                     70
- Two or more present:            100
"""

from __future__ import annotations

from pathlib import Path

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


# Files we recognise. Some live at root, some in .github/.
# Entries are (parts, is_dir_glob) where is_dir_glob=True means we check
# for any file matching a glob inside a directory.
_AGENT_DOC_FILES: tuple[tuple[str, ...], ...] = (
    ("AGENTS.md",),
    ("CLAUDE.md",),
    ("GEMINI.md",),
    # Windsurf
    (".windsurfrules",),
    # Cursor
    (".cursorrules",),
    # GitHub Copilot
    (".github", "copilot-instructions.md"),
    ("copilot-setup-steps.yml",),
    (".github", "copilot-setup-steps.yml"),
    # Aider
    (".aider.conf.yml",),
    # Zed
    (".zed", "settings.json"),
    # Bolt / StackBlitz
    (".bolt", "prompt"),
)

# Directories where any matching file counts as a hit
_AGENT_DOC_DIRS: tuple[tuple[tuple[str, ...], str], ...] = (
    ((".cursor", "rules"), "*.mdc"),
    # GitHub Copilot instructions directory (newer format)
    ((".github", "instructions"), "*.md"),
    # Windsurf rules directory
    ((".windsurf", "rules"), "*.md"),
)


def _resolve(ctx: RepoContext, parts: tuple[str, ...]) -> Path | None:
    """Return the relative path if it exists as a file, else None."""
    candidate = Path(*parts)
    if (ctx.root / candidate).is_file():
        return candidate
    return None


def _resolve_dir_glob(ctx: RepoContext, parts: tuple[str, ...], pattern: str) -> Path | None:
    """Return the relative dir path if it exists and contains files matching pattern."""
    candidate = Path(*parts)
    dir_path = ctx.root / candidate
    if dir_path.is_dir() and any(dir_path.glob(pattern)):
        return candidate
    return None


@register(
    check_id="agent_docs.present",
    pillar=Pillar.COGNITIVE_LOAD,
    title="Repo includes agent-targeted documentation",
    explanation="""
    Agent-targeted docs (AGENTS.md, CLAUDE.md, .cursorrules,
    .cursor/rules/*.mdc, .github/copilot-instructions.md,
    copilot-setup-steps.yml) encode conventions an agent would otherwise
    have to infer: branch naming, do-not-touch directories, commit message
    style, preferred libraries, and tool-specific configuration. A short
    doc here is one of the highest-leverage edits a maintainer can make.
    """,
)
def check(ctx: RepoContext) -> CheckResult:
    found: list[Path] = []
    for parts in _AGENT_DOC_FILES:
        rel = _resolve(ctx, parts)
        if rel is not None:
            found.append(rel)
    for parts, pattern in _AGENT_DOC_DIRS:
        rel = _resolve_dir_glob(ctx, parts, pattern)
        if rel is not None:
            found.append(rel)

    if not found:
        return CheckResult(
            check_id="agent_docs.present",
            pillar=Pillar.COGNITIVE_LOAD,
            score=0.0,
            findings=[Finding(
                check_id="agent_docs.present",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.WARN,
                message=(
                    "No agent-targeted docs found "
                    "(AGENTS.md / CLAUDE.md / .cursorrules / "
                    ".github/copilot-instructions.md / .cursor/rules/*.mdc)."
                ),
                fix_hint=(
                    "Add an AGENTS.md at the repo root with conventions, "
                    "do-not-touch paths, and the canonical test command."
                ),
            )],
        )

    score = 100.0 if len(found) >= 2 else 70.0
    info_finding = Finding(
        check_id="agent_docs.present",
        pillar=Pillar.COGNITIVE_LOAD,
        severity=Severity.INFO,
        file=found[0],
        message=f"Found agent-targeted docs: {', '.join(str(p) for p in found)}.",
    )
    return CheckResult(
        check_id="agent_docs.present",
        pillar=Pillar.COGNITIVE_LOAD,
        score=score,
        findings=[info_finding],
    )
