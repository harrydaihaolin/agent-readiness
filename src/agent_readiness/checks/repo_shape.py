"""Checks: repo_shape.*

Three checks that evaluate the shape of the repository from an agent's
perspective:
- How many files are at root level (cognitive overhead of orientation)
- How many files are "large" (hard to read in full)
- How many tokens does it cost to orient (context-window budget)
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


# ---------------------------------------------------------------------------
# Exclusions for repo_shape.large_files
# ---------------------------------------------------------------------------

# File suffixes that are never "source code" regardless of size.
# Flagging a 500-line lock file or a 2 MB PNG as "too large" is a false
# positive — these files can't be "split into smaller modules".
_LARGE_FILE_EXCLUDED_SUFFIXES: frozenset[str] = frozenset({
    # Images and media
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".bmp", ".tiff", ".tif", ".raw",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".mp3", ".wav", ".ogg", ".flac",
    # Binary / compiled / archive
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".whl", ".egg", ".jar", ".war",
    ".so", ".dylib", ".dll", ".exe", ".bin",
    ".db", ".sqlite", ".sqlite3",
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # Notebooks — large but intentional; a separate check can flag them
    ".ipynb",
})

# Exact filenames (case-sensitive) that are expected to be large.
_LARGE_FILE_EXCLUDED_NAMES: frozenset[str] = frozenset({
    # Dependency lock files — always generated, never manually split
    "poetry.lock", "uv.lock", "Cargo.lock", "go.sum",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "composer.lock", "Gemfile.lock", "pubspec.lock",
    "mix.lock", "flake.lock", "conda-lock.yml",
    # Generated XML / JSON (docs, sitemaps, OpenAPI specs in large repos)
    "sitemap.xml",
    # Dot-ignore templates — can be extremely long in template repositories
    ".gitignore",
    # pip freeze — not a true lockfile but valid to be large
    "requirements-freeze.txt",
})

# Filename glob patterns (matched against the basename only).
_LARGE_FILE_EXCLUDED_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Changelogs and release notes of any form
    re.compile(r"^CHANGE[S]?(LOG)?\.(md|rst|txt)$", re.IGNORECASE),
    re.compile(r"^HISTORY\.(md|rst|txt)$", re.IGNORECASE),
    re.compile(r"^RELEASES?\.(md|rst|txt)$", re.IGNORECASE),
    re.compile(r"^NEWS\.(md|rst|txt)$", re.IGNORECASE),
    # Migration / upgrade guides — expected to accumulate over time
    re.compile(r".*MIGRAT.*\.(md|rst|txt)$", re.IGNORECASE),
    re.compile(r".*UPGRADE.*\.(md|rst|txt)$", re.IGNORECASE),
    # Generated lock/hash files not covered by exact names above
    re.compile(r".*\.lock$", re.IGNORECASE),
    re.compile(r".*\.sum$", re.IGNORECASE),
)

# ---------------------------------------------------------------------------
# Exclusions for repo_shape.top_level_count
# ---------------------------------------------------------------------------

# Standard project-metadata files that every repo is expected to have at root.
# These don't add cognitive load — agents know what they are on sight.
_ROOT_META_STEMS = frozenset({
    "readme", "license", "licence", "copying",
    "changelog", "changes", "history", "news", "releases",
    "contributing", "contributors", "authors", "maintainers", "codeowners",
    "code_of_conduct", "security", "notice",
    "makefile", "rakefile", "gemfile", "procfile", "earthfile",
    "dockerfile",
})


def _is_root_meta(name: str) -> bool:
    """Return True if this root file is standard project metadata."""
    return name.lower().split(".")[0] in _ROOT_META_STEMS


@register(
    check_id="repo_shape.top_level_count",
    pillar=Pillar.COGNITIVE_LOAD,
    title="Few files at repo root (orientation overhead)",
    explanation="""
    When an agent first enters a repository it scans the root directory. A
    root with dozens of files imposes a high navigation cost: the agent must
    read or at least skim each file to decide whether it's relevant to the
    task. Keeping the root lean (≤10 non-hidden files) means the agent can
    orient quickly. Standard project-metadata files (README, LICENSE,
    CHANGELOG, CONTRIBUTING, Makefile, Dockerfile) are excluded from the
    count — agents recognise these on sight.
    """,
    weight=0.8,
)
def check_top_level_count(ctx: RepoContext) -> CheckResult:
    # Count non-hidden root files, excluding well-known metadata files that
    # every project is expected to have and that agents recognise on sight.
    count = sum(
        1 for f in ctx._files
        if len(f.parts) == 1
        and not f.name.startswith(".")
        and not _is_root_meta(f.name)
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


def _is_excluded_from_large_check(f: Path) -> bool:
    """Return True if this file should not be flagged as 'large'."""
    name = f.name
    suffix = f.suffix.lower()
    # Exclude by file extension (images, binaries, lock file suffixes, etc.)
    if suffix in _LARGE_FILE_EXCLUDED_SUFFIXES:
        return True
    # Exclude by exact filename
    if name in _LARGE_FILE_EXCLUDED_NAMES:
        return True
    # Exclude by filename pattern (changelogs, migrations, etc.)
    for pattern in _LARGE_FILE_EXCLUDED_PATTERNS:
        if pattern.match(name):
            return True
    return False


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
        # Skip files that are expected to be large (not source code)
        if _is_excluded_from_large_check(f):
            continue
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

    # Default warn threshold raised to 24K (from 16K) to reflect modern agent
    # context windows (128K+). 16K fired too aggressively on well-documented
    # frameworks. Max raised to 120K to keep scoring proportional.
    warn_threshold = int(ctx.context_config.get("token_budget_warn", 24_000))
    max_threshold = int(ctx.context_config.get("token_budget_max", 120_000))

    half_warn = warn_threshold // 2
    double_warn = warn_threshold * 2
    half_max = max_threshold // 2

    if tokens < half_warn:
        score = 100.0
    elif tokens < warn_threshold:
        score = 80.0
    elif tokens < double_warn:
        score = 60.0
    elif tokens < half_max:
        score = 40.0
    else:
        score = 0.0

    findings: list[Finding] = []
    if tokens > warn_threshold:
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
