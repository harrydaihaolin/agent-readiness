"""Check: entry_points.detected

An agent needs to know where to start. If a repository has no obvious
entry point, the agent has to infer the starting point from filenames,
imports, and README prose — error-prone and slow. Having a clear entry
point (main.py, index.js, cmd/ directory, etc.) means the agent can
start running the code immediately.
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


_ENTRY_POINT_NAMES = {
    # Python
    "main.py", "app.py", "server.py", "wsgi.py", "asgi.py",
    # JavaScript / TypeScript
    "index.js", "index.ts", "index.mjs",
    # Go / Rust
    "main.go", "main.rs",
}

_ENTRY_SEARCH_DIRS = ("", "src")   # root, or src/


@register(
    check_id="entry_points.detected",
    pillar=Pillar.COGNITIVE_LOAD,
    title="Clear entry point detected",
    explanation="""
    Agents start by finding out how to run the code. A well-named entry
    point (main.py, index.js, cmd/, etc.) provides an unambiguous start.
    Without one the agent has to guess, which adds friction and risk of
    hallucination.
    """,
    weight=0.8,
)
def check_entry_points_detected(ctx: RepoContext) -> CheckResult:
    found: list[str] = []

    # Check named entry point files at root or src/
    for dirname in _ENTRY_SEARCH_DIRS:
        for name in _ENTRY_POINT_NAMES:
            candidate = (name if not dirname else f"{dirname}/{name}")
            if (ctx.root / candidate).is_file():
                found.append(candidate)

    # Check cmd/ or bin/ directory with at least one file
    for dirn in ("cmd", "bin"):
        dirpath = ctx.root / dirn
        if dirpath.is_dir():
            has_files = any(True for p in dirpath.iterdir() if p.is_file())
            if has_files:
                found.append(f"{dirn}/")

    # Check __main__.py anywhere in the repo
    for f in ctx._files:
        if f.name == "__main__.py":
            found.append(str(f))

    if found:
        return CheckResult(
            check_id="entry_points.detected",
            pillar=Pillar.COGNITIVE_LOAD,
            score=100.0,
            weight=0.8,
            findings=[Finding(
                check_id="entry_points.detected",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.INFO,
                message=f"Entry point(s) found: {', '.join(found[:5])}",
            )],
        )

    return CheckResult(
        check_id="entry_points.detected",
        pillar=Pillar.COGNITIVE_LOAD,
        score=0.0,
        weight=0.8,
        findings=[Finding(
            check_id="entry_points.detected",
            pillar=Pillar.COGNITIVE_LOAD,
            severity=Severity.WARN,
            message="No entry point found (main.py, index.js, cmd/, bin/, __main__.py, etc.).",
            fix_hint="Add a main.py, index.js, or similar entry point so agents know where to start.",
        )],
    )
