"""Private matcher: ``manifest_introspection``.

Detects whether the repo has a recognised project manifest at the
root or, for monorepos, at depth ≤ ``monorepo_depth``. Fires when no
manifest is found anywhere in scope. Used by ``manifest.detected``.
"""

from __future__ import annotations

from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher

# Standard fixed-name manifests across ecosystems.
_ROOT_MANIFESTS: tuple[str, ...] = (
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
    "global.json",
    "deno.json", "deno.jsonc",
    "stack.yaml", "cabal.project",
    "flake.nix", "default.nix",
    "CMakeLists.txt",
    "WORKSPACE", "WORKSPACE.bazel",
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
)

# Suffix-driven manifests (.NET project files, .cabal, .gemspec).
_MANIFEST_SUFFIXES_AT_ROOT_OR_SHALLOW: tuple[str, ...] = (
    ".csproj", ".fsproj", ".vbproj", ".sln",
    ".cabal", ".gemspec",
)

# Subset of manifests that count when found at depth==2 (monorepo layout).
_MONOREPO_MANIFESTS: frozenset[str] = frozenset({
    "pyproject.toml", "package.json", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
})


def match_manifest_introspection(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    mode = str(cfg.get("mode", "any_manifest_present"))
    if mode != "any_manifest_present":
        return []
    monorepo_depth = int(cfg.get("monorepo_depth", 2))

    # Fixed-name manifests at root.
    for name in _ROOT_MANIFESTS:
        if (ctx.root / name).is_file():
            return []

    # Suffix-driven manifests at root or shallow.
    for f in ctx._files:
        if f.suffix in _MANIFEST_SUFFIXES_AT_ROOT_OR_SHALLOW and len(f.parts) <= 2:
            return []

    # Monorepo layout: depth==2 manifests.
    if monorepo_depth >= 2:
        for f in ctx._files:
            if len(f.parts) == 2 and f.name in _MONOREPO_MANIFESTS:
                return []

    return [(
        None, None,
        "No project manifest found (pyproject.toml, package.json, Cargo.toml, go.mod, ...).",
    )]


register_private_matcher("manifest_introspection", match_manifest_introspection)
