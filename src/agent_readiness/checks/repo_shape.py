"""Checks: repo_shape.*

Three checks that evaluate the shape of the repository from an agent's
perspective:
- How many files are at root level (cognitive overhead of orientation)
- How many files are "large" (hard to read in full)
- How many tokens does it cost to orient (context-window budget)
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


@register(
    check_id="repo_shape.top_level_count",
    pillar=Pillar.COGNITIVE_LOAD,
    title="Few files at repo root (orientation overhead)",
    explanation="""
    When an agent first enters a repository it scans the root directory. A
    root with dozens of files imposes a high navigation cost: the agent must
    read or at least skim each file to decide whether it's relevant to the
    task. Keeping the root lean (≤10 non-hidden files) means the agent can
    orient quickly.
    """,
    weight=0.8,
)
def check_top_level_count(ctx: RepoContext) -> CheckResult:
    # Count non-hidden, non-directory files at root level
    count = sum(
        1 for f in ctx._files
        if len(f.parts) == 1 and not f.name.startswith(".")
    )

    if count <= 10:
        score = 100.0
    elif count <= 20:
        score = 80.0
    elif count <= 30:
        score = 60.0
    elif count <= 50:
        score = 40.0
    else:
        score = 0.0

    findings: list[Finding] = []
    if count > 20:
        findings.append(Finding(
            check_id="repo_shape.top_level_count",
            pillar=Pillar.COGNITIVE_LOAD,
            severity=Severity.WARN,
            message=f"Repo root has {count} non-hidden files — consider organising into subdirectories.",
            fix_hint="Move files into src/, docs/, scripts/ etc. to reduce root clutter.",
        ))

    return CheckResult(
        check_id="repo_shape.top_level_count",
        pillar=Pillar.COGNITIVE_LOAD,
        score=score,
        weight=0.8,
        findings=findings,
    )


@register(
    check_id="repo_shape.large_files",
    pillar=Pillar.COGNITIVE_LOAD,
    title="Few large files (context-window friendly)",
    explanation="""
    Files larger than 500 lines or 50 KB are difficult for agents to read
    in full without exceeding context-window limits. Large files also suggest
    low cohesion: too much responsibility in one place. Keeping files small
    means agents can read entire modules without truncation.
    """,
    weight=0.8,
)
def check_large_files(ctx: RepoContext) -> CheckResult:
    large: list[str] = []
    for f in ctx._files:
        full_path = ctx.root / f
        try:
            size = full_path.stat().st_size
        except OSError:
            continue
        if size > 50_000:
            large.append(str(f))
            continue
        # Line count — read up to 256KB
        text = ctx.read_text(f, max_bytes=256_000)
        if text is not None and text.count("\n") > 500:
            large.append(str(f))

    n = len(large)
    if n == 0:
        score = 100.0
    elif n <= 2:
        score = 80.0
    elif n <= 5:
        score = 60.0
    elif n <= 10:
        score = 30.0
    else:
        score = 0.0

    findings: list[Finding] = []
    for path_str in large[:5]:
        findings.append(Finding(
            check_id="repo_shape.large_files",
            pillar=Pillar.COGNITIVE_LOAD,
            severity=Severity.WARN,
            file=path_str,
            message=f"Large file: {path_str} (>500 lines or >50 KB).",
            fix_hint="Split large files into smaller, focused modules.",
        ))

    return CheckResult(
        check_id="repo_shape.large_files",
        pillar=Pillar.COGNITIVE_LOAD,
        score=score,
        weight=0.8,
        findings=findings,
    )


@register(
    check_id="repo_shape.token_budget",
    pillar=Pillar.COGNITIVE_LOAD,
    title="Orientation fits in agent context window",
    explanation="""
    Agents orient in a repo by reading README, manifest, and top-level source
    files. If that orientation material exceeds ~16k tokens, the agent can't
    fit full context into a typical coding-agent session window without
    summarisation. This check estimates the token cost of basic orientation.
    """,
    weight=0.7,
)
def check_token_budget(ctx: RepoContext) -> CheckResult:
    tokens = ctx.orientation_tokens

    if tokens < 8_000:
        score = 100.0
    elif tokens < 16_000:
        score = 80.0
    elif tokens < 32_000:
        score = 60.0
    elif tokens < 64_000:
        score = 40.0
    else:
        score = 0.0

    findings: list[Finding] = []
    if tokens > 16_000:
        findings.append(Finding(
            check_id="repo_shape.token_budget",
            pillar=Pillar.COGNITIVE_LOAD,
            severity=Severity.WARN,
            message=(
                f"Estimated orientation cost is ~{tokens:,} tokens — "
                "may exceed agent context window."
            ),
            fix_hint=(
                "Trim README or add a concise AGENTS.md that summarises the "
                "repo structure in <2k tokens."
            ),
        ))

    return CheckResult(
        check_id="repo_shape.token_budget",
        pillar=Pillar.COGNITIVE_LOAD,
        score=score,
        weight=0.7,
        findings=findings,
    )
