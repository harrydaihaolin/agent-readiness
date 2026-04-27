"""Checks: git.churn_hotspots and code.complexity

git.churn_hotspots: Files that change frequently AND are large are
"hotspots" — they're hard to understand and modify correctly. An agent
working in a hotspot has a higher chance of introducing regressions.

code.complexity: High cyclomatic complexity means more paths through the
code, harder-to-predict behaviour, and more test cases needed. An agent
generating code with high complexity is harder to test and review.
"""

from __future__ import annotations

import subprocess

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


@register(
    check_id="git.churn_hotspots",
    pillar=Pillar.COGNITIVE_LOAD,
    title="No high-churn large files (hotspots)",
    explanation="""
    Files that are both frequently changed (>10 commits) and large (>200
    lines) are "hotspots" — they concentrate risk. When an agent modifies
    a hotspot, it's more likely to introduce a regression because the file
    has many existing behaviours to preserve. Hotspots also tend to have
    unclear ownership and intertwined concerns.
    """,
    weight=0.6,
)
def check_churn_hotspots(ctx: RepoContext) -> CheckResult:
    # Skip if fewer than 5 commits (not enough history to measure churn)
    if ctx.commit_count < 5:
        return CheckResult(
            check_id="git.churn_hotspots",
            pillar=Pillar.COGNITIVE_LOAD,
            score=0.0,
            weight=0.6,
            not_measured=True,
            findings=[Finding(
                check_id="git.churn_hotspots",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.INFO,
                message=(
                    f"Only {ctx.commit_count} commits — not enough history "
                    "to measure churn hotspots."
                ),
            )],
        )

    # Run git log --numstat
    try:
        result = subprocess.run(
            ["git", "log", "--numstat", "--pretty=format:", "--", "."],
            cwd=ctx.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return CheckResult(
            check_id="git.churn_hotspots",
            pillar=Pillar.COGNITIVE_LOAD,
            score=0.0,
            weight=0.6,
            not_measured=True,
            findings=[Finding(
                check_id="git.churn_hotspots",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.INFO,
                message="Could not run git log for churn analysis.",
            )],
        )

    # Parse numstat output: "<additions>\t<deletions>\t<filename>"
    change_count: dict[str, int] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        additions, deletions, filename = parts[0], parts[1], parts[2]
        # Binary files show "-"
        if additions == "-" or deletions == "-":
            continue
        # Ignore renames (contain " => ")
        if " => " in filename:
            continue
        change_count[filename] = change_count.get(filename, 0) + 1

    # Identify hotspots: changed >10 times AND file has >200 lines
    hotspots: list[str] = []
    for filename, count in change_count.items():
        if count <= 10:
            continue
        full_path = ctx.root / filename
        if not full_path.is_file():
            continue
        text = ctx.read_text(filename, max_bytes=256_000)
        if text is not None and text.count("\n") > 200:
            hotspots.append((filename, count))

    hotspots.sort(key=lambda x: x[1], reverse=True)

    n = len(hotspots)
    if n == 0:
        score = 100.0
    elif n <= 2:
        # Mild (10-20 changes) vs severe (>20 changes)
        max_churn = max(c for _, c in hotspots)
        score = 80.0 if max_churn <= 20 else 60.0
    else:
        score = 0.0

    findings: list[Finding] = []
    for filename, count in hotspots[:5]:
        findings.append(Finding(
            check_id="git.churn_hotspots",
            pillar=Pillar.COGNITIVE_LOAD,
            severity=Severity.WARN,
            file=filename,
            message=f"Hotspot: {filename} changed {count} times and is >200 lines.",
            fix_hint="Consider splitting this file into smaller, focused modules.",
        ))

    return CheckResult(
        check_id="git.churn_hotspots",
        pillar=Pillar.COGNITIVE_LOAD,
        score=score,
        weight=0.6,
        findings=findings,
    )


@register(
    check_id="code.complexity",
    pillar=Pillar.COGNITIVE_LOAD,
    title="Code cyclomatic complexity is low",
    explanation="""
    High cyclomatic complexity (many branches, loops, exception handlers)
    in a function means more paths through the code. An agent generating
    changes to a complex function has more edge cases to reason about and
    more ways to introduce a bug. Keeping functions simple (complexity < 5)
    makes agent-generated diffs safer and easier to review.
    """,
    weight=0.7,
)
def check_code_complexity(ctx: RepoContext) -> CheckResult:
    try:
        import lizard  # type: ignore[import]
    except ImportError:
        return CheckResult(
            check_id="code.complexity",
            pillar=Pillar.COGNITIVE_LOAD,
            score=0.0,
            weight=0.7,
            not_measured=True,
            findings=[Finding(
                check_id="code.complexity",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.INFO,
                message="Install lizard for complexity analysis: pip install lizard",
            )],
        )

    # Scan Python/JS/TS/Go/Java files
    _EXT = {".py", ".js", ".ts", ".go", ".java"}
    files_to_scan = [
        str(ctx.root / f) for f in ctx._files if f.suffix in _EXT
    ]

    if not files_to_scan:
        return CheckResult(
            check_id="code.complexity",
            pillar=Pillar.COGNITIVE_LOAD,
            score=100.0,
            weight=0.7,
            not_measured=True,
        )

    total_complexity = 0.0
    total_functions = 0
    high_complexity: list[tuple[str, str, int]] = []  # (file, func, cc)

    for filepath in files_to_scan:
        try:
            file_info = lizard.analyze_file(filepath)
        except Exception:  # noqa: BLE001
            continue
        for func in file_info.function_list:
            cc = func.cyclomatic_complexity
            total_complexity += cc
            total_functions += 1
            if cc > 15:
                rel = filepath.replace(str(ctx.root) + "/", "")
                high_complexity.append((rel, func.name, cc))

    if total_functions == 0:
        return CheckResult(
            check_id="code.complexity",
            pillar=Pillar.COGNITIVE_LOAD,
            score=100.0,
            weight=0.7,
        )

    avg = total_complexity / total_functions

    if avg < 5:
        score = 100.0
    elif avg < 8:
        score = 80.0
    elif avg < 12:
        score = 60.0
    else:
        score = 0.0

    high_complexity.sort(key=lambda x: x[2], reverse=True)
    findings: list[Finding] = []
    for rel_file, func_name, cc in high_complexity[:5]:
        findings.append(Finding(
            check_id="code.complexity",
            pillar=Pillar.COGNITIVE_LOAD,
            severity=Severity.WARN,
            file=rel_file,
            message=f"Function '{func_name}' has cyclomatic complexity {cc}.",
            fix_hint="Refactor into smaller functions with a single responsibility.",
        ))

    return CheckResult(
        check_id="code.complexity",
        pillar=Pillar.COGNITIVE_LOAD,
        score=score,
        weight=0.7,
        findings=findings,
    )
