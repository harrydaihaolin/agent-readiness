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
    "main.py", "app.py", "server.py", "wsgi.py", "asgi.py", "cli.py",
    "run.py", "start.py", "manage.py",   # Django manage.py, Flask run.py
    # JavaScript / TypeScript
    "index.js", "index.ts", "index.mjs", "index.cjs",
    "app.js", "app.ts", "server.js", "server.ts",
    # Go / Rust
    "main.go", "main.rs",
    # C / C++
    "main.c", "main.cpp", "main.cc",
    # Ruby
    "main.rb", "app.rb", "config.ru",  # Rack entry point
    # Java / Kotlin / Scala
    "Main.java", "Main.kt", "Application.java", "Application.kt",
    "App.java", "App.kt", "App.scala", "Main.scala",
    # C# / .NET
    "Program.cs",
    # PHP
    "index.php", "app.php",
    # Swift
    "main.swift",
}

_ENTRY_SEARCH_DIRS = ("", "src", "app", "src/main", "src/main/java", "src/main/kotlin",
                      "src/main/scala", "src/main/csharp")


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

    # Check cmd/ or bin/ directory — any content (files OR subdirs) counts.
    # Go monorepos put commands in cmd/<name>/main.go, so cmd/ may only
    # contain subdirectories at the top level.
    for dirn in ("cmd", "bin", "cli"):
        dirpath = ctx.root / dirn
        if dirpath.is_dir() and any(dirpath.iterdir()):
            found.append(f"{dirn}/")

    # Check __main__.py anywhere in the repo
    for f in ctx._files:
        if f.name == "__main__.py":
            found.append(str(f))

    # Check pyproject.toml for declared console_scripts / scripts entry points
    pyproject = ctx.read_text("pyproject.toml")
    if pyproject and ("[project.scripts]" in pyproject
                      or "[project.gui-scripts]" in pyproject
                      or "console_scripts" in pyproject
                      or "[tool.poetry.scripts]" in pyproject):
        found.append("pyproject.toml [scripts]")

    # Check package.json "main" or "exports" field — indicates a published library entry point
    pkg_text = ctx.read_text("package.json")
    if pkg_text:
        try:
            import json as _json
            pkg = _json.loads(pkg_text)
            if "main" in pkg or "exports" in pkg or "module" in pkg:
                found.append("package.json (main/exports/module field)")
        except Exception:
            pass

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

    # Partial credit: a proper Python/Rust/Go library package is meant to be
    # imported, not run directly. Score 60 (WARN) instead of 0 so a library
    # repo isn't penalised for the absence of a runtime entry point.
    is_library = (
        (ctx.root / "pyproject.toml").is_file()
        or (ctx.root / "Cargo.toml").is_file()
        or (ctx.root / "go.mod").is_file()
        or (ctx.root / "pom.xml").is_file()
        or (ctx.root / "build.gradle").is_file()
        or (ctx.root / "Gemfile").is_file()
        or any(f.name == "__init__.py" and len(f.parts) <= 2 for f in ctx._files)
    )
    if is_library:
        return CheckResult(
            check_id="entry_points.detected",
            pillar=Pillar.COGNITIVE_LOAD,
            score=60.0,
            weight=0.8,
            findings=[Finding(
                check_id="entry_points.detected",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.WARN,
                message=(
                    "No explicit entry point found — this appears to be a library "
                    "(imported, not run directly). Add a CLI entry point or "
                    "[project.scripts] in pyproject.toml if agents should be able "
                    "to invoke it directly."
                ),
                fix_hint=(
                    "For a CLI, add main.py or declare [project.scripts] in pyproject.toml. "
                    "For a pure library this warning can be ignored."
                ),
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
