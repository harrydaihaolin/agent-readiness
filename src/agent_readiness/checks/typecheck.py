"""Check: typecheck.configured

Type checking (mypy, pyright, TypeScript, etc.) gives agents a fast
feedback loop on type correctness. Without it, a type error in generated
code may not surface until runtime — possibly deep inside a test run or
production execution. A configured type checker means the agent can run
`mypy .` or `tsc --noEmit` and get immediate feedback.
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


_TYPECHECK_FILES = (
    "mypy.ini", ".mypy.ini",
    "pyrightconfig.json",
    ".flowconfig",
    "tsconfig.json",
)

_PYPROJECT_SECTIONS = ("[tool.mypy]", "[tool.pyright]")

# Manifests that imply a statically-typed language — the compiler IS the
# type checker; asking for a separate type-checker config is a false positive.
_STATIC_LANG_MANIFESTS: tuple[tuple[str, str], ...] = (
    ("go.mod",            "Go (statically typed)"),
    ("Cargo.toml",        "Rust (statically typed)"),
    ("CMakeLists.txt",    "C/C++ (statically typed)"),
    ("Package.swift",     "Swift (statically typed)"),
    # JVM — Java, Kotlin, Groovy, Scala are all statically typed
    ("pom.xml",           "Java/Maven (statically typed)"),
    ("build.gradle",      "JVM/Gradle (statically typed)"),
    ("build.gradle.kts",  "Kotlin/Gradle (statically typed)"),
    ("build.sbt",         "Scala/SBT (statically typed)"),
)


@register(
    check_id="typecheck.configured",
    pillar=Pillar.FEEDBACK,
    title="Type checker is configured",
    explanation="""
    A configured type checker (mypy, pyright, tsc) provides sub-second
    feedback on type correctness without running the full test suite. For
    agents that make many small changes, this fast feedback loop reduces
    hallucinated type errors and catches integration mistakes early. Without
    a type checker the agent must infer types from context — error-prone
    and slow.
    """,
    weight=0.9,
)
def check_typecheck_configured(ctx: RepoContext) -> CheckResult:
    # Check for dedicated config files
    for name in _TYPECHECK_FILES:
        if (ctx.root / name).is_file():
            return CheckResult(
                check_id="typecheck.configured",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                weight=0.9,
                findings=[Finding(
                    check_id="typecheck.configured",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message=f"Type checker config found: {name}",
                )],
            )

    # tsconfig.*.json variants at repo root (e.g. tsconfig.base.json, tsconfig.app.json)
    for f in ctx._files:
        if (
            len(f.parts) == 1
            and f.name.startswith("tsconfig")
            and f.suffix == ".json"
        ):
            return CheckResult(
                check_id="typecheck.configured",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                weight=0.9,
                findings=[Finding(
                    check_id="typecheck.configured",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message=f"TypeScript config found: {f.name}",
                )],
            )

    # Check pyproject.toml for [tool.mypy] or [tool.pyright]
    pyproject = ctx.read_text("pyproject.toml")
    if pyproject:
        for section in _PYPROJECT_SECTIONS:
            if section in pyproject:
                return CheckResult(
                    check_id="typecheck.configured",
                    pillar=Pillar.FEEDBACK,
                    score=100.0,
                    weight=0.9,
                    findings=[Finding(
                        check_id="typecheck.configured",
                        pillar=Pillar.FEEDBACK,
                        severity=Severity.INFO,
                        message=f"Type checker configured in pyproject.toml ({section})",
                    )],
                )

    # setup.cfg [mypy] section (classic mypy config location)
    setup_cfg = ctx.read_text("setup.cfg")
    if setup_cfg and "[mypy]" in setup_cfg:
        return CheckResult(
            check_id="typecheck.configured",
            pillar=Pillar.FEEDBACK,
            score=100.0,
            weight=0.9,
            findings=[Finding(
                check_id="typecheck.configured",
                pillar=Pillar.FEEDBACK,
                severity=Severity.INFO,
                message="mypy configured in setup.cfg ([mypy] section)",
            )],
        )

    # py.typed marker file (PEP 561) — indicates a typed Python package
    for f in ctx._files:
        if f.name == "py.typed":
            return CheckResult(
                check_id="typecheck.configured",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                weight=0.9,
                findings=[Finding(
                    check_id="typecheck.configured",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message="py.typed marker found — PEP 561 typed package",
                )],
            )

    # .NET / C# projects — any .csproj/.fsproj/.vbproj signals a statically-typed project
    for f in ctx._files:
        if f.suffix in (".csproj", ".fsproj", ".vbproj"):
            return CheckResult(
                check_id="typecheck.configured",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                weight=0.9,
                findings=[Finding(
                    check_id="typecheck.configured",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message=f"Type checking provided by language: .NET/C# (statically typed) [{f.name}]",
                )],
            )

    # Statically-typed languages: the compiler enforces types; a separate
    # type-checker config file is not expected or required.
    for manifest, lang_label in _STATIC_LANG_MANIFESTS:
        if (ctx.root / manifest).is_file():
            return CheckResult(
                check_id="typecheck.configured",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                weight=0.9,
                findings=[Finding(
                    check_id="typecheck.configured",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message=f"Type checking provided by language: {lang_label}",
                )],
            )

    return CheckResult(
        check_id="typecheck.configured",
        pillar=Pillar.FEEDBACK,
        score=0.0,
        weight=0.9,
        findings=[Finding(
            check_id="typecheck.configured",
            pillar=Pillar.FEEDBACK,
            severity=Severity.WARN,
            message="No type checker configuration found.",
            fix_hint=(
                "Add mypy.ini or pyrightconfig.json, or configure [tool.mypy] "
                "in pyproject.toml for fast type-checking feedback."
            ),
        )],
    )
