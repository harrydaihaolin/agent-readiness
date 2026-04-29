"""Checks: manifest.detected and manifest.lockfile_present

A project manifest (pyproject.toml, package.json, etc.) tells an agent
*what* a project is. A lockfile tells it *exactly what versions* are
installed. Both are essential for reproducible agent runs.
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


_MANIFESTS = (
    "pyproject.toml", "setup.py", "setup.cfg",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "mix.exs",
    "composer.json",
    "pubspec.yaml",
    "Package.swift",
)

_LOCKFILES = (
    "poetry.lock", "uv.lock",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "composer.lock",
    "pubspec.lock",
    "flake.lock",
    "mix.lock",
    # Conda / pixi ecosystem
    "conda-lock.yml", "conda-lock.yaml",
    "pixi.lock",
)


@register(
    check_id="manifest.detected",
    pillar=Pillar.FEEDBACK,
    title="Project manifest file detected",
    explanation="""
    A package manifest (pyproject.toml, package.json, Cargo.toml, etc.) tells
    an agent what ecosystem this project lives in, which dependencies it needs,
    and how to build/install it. Without one the agent has to guess the language
    and install path, which degrades reliability.
    """,
    weight=1.0,
)
def check_manifest_detected(ctx: RepoContext) -> CheckResult:
    for name in _MANIFESTS:
        if ctx.has_file(name, case_insensitive=False) is not None:
            return CheckResult(
                check_id="manifest.detected",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                findings=[Finding(
                    check_id="manifest.detected",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message=f"Project manifest found: {name}",
                )],
            )

    return CheckResult(
        check_id="manifest.detected",
        pillar=Pillar.FEEDBACK,
        score=0.0,
        findings=[Finding(
            check_id="manifest.detected",
            pillar=Pillar.FEEDBACK,
            severity=Severity.WARN,
            message="No project manifest found (pyproject.toml, package.json, etc.).",
            fix_hint="Add a package manifest so agents know the project's dependencies.",
        )],
    )


@register(
    check_id="manifest.lockfile_present",
    pillar=Pillar.FEEDBACK,
    title="Dependency lockfile present",
    explanation="""
    A lockfile (poetry.lock, uv.lock, package-lock.json, etc.) pins exact
    dependency versions so that `install` commands are deterministic across
    machines and agent runs. Without a lockfile an agent may encounter
    version conflicts, subtle behavioural differences, or install failures
    that don't happen for the original developer.
    """,
    weight=1.0,
)
def check_lockfile_present(ctx: RepoContext) -> CheckResult:
    for name in _LOCKFILES:
        if ctx.has_file(name, case_insensitive=False) is not None:
            return CheckResult(
                check_id="manifest.lockfile_present",
                pillar=Pillar.FEEDBACK,
                score=100.0,
                findings=[Finding(
                    check_id="manifest.lockfile_present",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message=f"Lockfile found: {name}",
                )],
            )

    # Conda environment files — pinned when created with `conda env export`
    for name in ("environment.yml", "environment.yaml"):
        if ctx.has_file(name, case_insensitive=False) is not None:
            return CheckResult(
                check_id="manifest.lockfile_present",
                pillar=Pillar.FEEDBACK,
                score=80.0,
                findings=[Finding(
                    check_id="manifest.lockfile_present",
                    pillar=Pillar.FEEDBACK,
                    severity=Severity.INFO,
                    message=f"Conda environment file found: {name}",
                    fix_hint="For full reproducibility, consider also generating a conda-lock.yml.",
                )],
            )

    # requirements.txt is a semi-lockfile — better than nothing
    if ctx.has_file("requirements.txt", case_insensitive=False) is not None:
        return CheckResult(
            check_id="manifest.lockfile_present",
            pillar=Pillar.FEEDBACK,
            score=70.0,
            findings=[Finding(
                check_id="manifest.lockfile_present",
                pillar=Pillar.FEEDBACK,
                severity=Severity.INFO,
                message="Only requirements.txt found — not a true lockfile (no pinned hashes).",
                fix_hint="Consider switching to uv.lock or poetry.lock for fully reproducible installs.",
            )],
        )

    return CheckResult(
        check_id="manifest.lockfile_present",
        pillar=Pillar.FEEDBACK,
        score=0.0,
        findings=[Finding(
            check_id="manifest.lockfile_present",
            pillar=Pillar.FEEDBACK,
            severity=Severity.WARN,
            message="No lockfile found. Dependency installs may not be reproducible.",
            fix_hint="Run `uv lock` / `npm install` / `cargo build` to generate a lockfile.",
        )],
    )
