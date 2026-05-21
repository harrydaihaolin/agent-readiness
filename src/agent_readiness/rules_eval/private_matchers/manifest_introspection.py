"""Private matcher: ``manifest_introspection``.

Detects whether the repo has a recognised project manifest at the
root or, for monorepos, at depth ≤ ``monorepo_depth``. Fires when no
manifest is found anywhere in scope. Used by ``manifest.detected``.
"""

from __future__ import annotations

from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher

# Standard fixed-name manifests across ecosystems. Mirrors the language
# table in ``context_probe._LANGUAGE_BY_MANIFEST`` so anything the engine
# can probe a language for is *also* a recognised manifest here — i.e.
# the matcher does not under-fire on Scala / Clojure / Erlang / OCaml /
# Julia / R / Perl repos just because their canonical manifest name
# isn't in this tuple.
_ROOT_MANIFESTS: tuple[str, ...] = (
    # Python.
    "pyproject.toml", "setup.py", "setup.cfg",
    "Pipfile",
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
    # JS / TS / Deno.
    "package.json",
    "deno.json", "deno.jsonc",
    "tsconfig.json",
    # Rust.
    "Cargo.toml",
    # Go.
    "go.mod",
    # Ruby.
    "Gemfile",
    # PHP.
    "composer.json",
    # JVM (Java / Kotlin / Scala) — Maven, Gradle, SBT, Mill, Bazel.
    "pom.xml", "build.gradle", "build.gradle.kts",
    "build.sbt", "build.sc",
    "WORKSPACE", "WORKSPACE.bazel",
    # Elixir.
    "mix.exs",
    # Swift.
    "Package.swift",
    # Dart / Flutter.
    "pubspec.yaml",
    # Clojure.
    "project.clj", "deps.edn",
    # Erlang.
    "rebar.config",
    # OCaml.
    "dune-project",
    # Julia.
    "Project.toml",
    # R.
    "DESCRIPTION",
    # Perl.
    "Makefile.PL", "cpanfile",
    # Haskell.
    "stack.yaml", "cabal.project",
    # .NET (also see ``_MANIFEST_SUFFIXES_AT_ROOT_OR_SHALLOW`` below).
    "global.json",
    # Nix-managed repos.
    "flake.nix", "default.nix",
    # C / C++.
    "CMakeLists.txt",
)

# Suffix-driven manifests (.NET project files, .cabal, .gemspec).
_MANIFEST_SUFFIXES_AT_ROOT_OR_SHALLOW: tuple[str, ...] = (
    ".csproj", ".fsproj", ".vbproj", ".sln",
    ".cabal", ".gemspec",
)

# Subset of manifests that count when found at depth==2 (monorepo layout).
# Same shape as ``_ROOT_MANIFESTS`` but limited to the manifests we
# actually see at ``packages/<name>/<manifest>`` style depth-2 paths in
# the wild (Python, JS, Rust, Go, JVM). Adding the JVM trio (`pom.xml`,
# `build.gradle*`, `build.sbt`) keeps the matcher in sync with how Scala
# / Java monorepos actually lay out their modules.
_MONOREPO_MANIFESTS: frozenset[str] = frozenset({
    "pyproject.toml", "package.json", "Cargo.toml",
    "go.mod",
    "pom.xml", "build.gradle", "build.gradle.kts", "build.sbt",
    "deps.edn", "project.clj",
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
