"""RepoContext: cached, read-only view of a repository for checks to consume.

Built once per scan; checks should pull from this rather than re-walking the tree.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

# Directories we never recurse into. Generated/vendored code shouldn't count
# against the repo's agent-readiness score.
_EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "vendor", "third_party",
    ".venv", "venv", "env",
    "dist", "build", "target", "out",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".next", ".nuxt", ".cache",
})


@dataclass
class RepoContext:
    """A cached snapshot of a repository on disk."""
    root: Path
    context_config: dict = field(default_factory=dict)  # from [context] in .agent-readiness.toml
    _files: list[Path] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"{self.root} is not a directory")
        self._files = list(self._walk(self.root))

    # --- file inventory ---------------------------------------------------

    def _walk(self, base: Path):
        """Yield every non-excluded file under base, relative paths."""
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            # Skip if any segment is in the exclusion set.
            if any(part in _EXCLUDED_DIRS for part in path.relative_to(base).parts):
                continue
            yield path.relative_to(base)

    @property
    def files(self) -> list[Path]:
        """All non-excluded files, paths relative to the repo root."""
        return list(self._files)

    def read_text(self, rel_path: Path | str, max_bytes: int = 256_000) -> str | None:
        """Read a file (relative to repo root) as UTF-8 text.

        Returns None if the file doesn't exist or isn't decodable. Caps the
        read at *max_bytes* to keep a single pathological file from blowing
        memory. Checks should use this rather than open() so all reads
        share one policy.
        """
        path = self.root / rel_path
        if not path.is_file():
            return None
        try:
            with path.open("rb") as f:
                blob = f.read(max_bytes + 1)
        except OSError:
            return None
        try:
            return blob[:max_bytes].decode("utf-8", errors="replace")
        except (UnicodeDecodeError, LookupError):
            return None

    def has_file(self, *names: str, case_insensitive: bool = True) -> Path | None:
        """Return the first matching top-level file, or None.

        Useful for README/AGENTS.md/etc. detection.
        """
        wanted = {n.lower() for n in names} if case_insensitive else set(names)
        for f in self._files:
            if len(f.parts) != 1:
                continue
            name = f.name.lower() if case_insensitive else f.name
            if name in wanted:
                return f
        return None

    # --- git --------------------------------------------------------------

    @cached_property
    def is_git_repo(self) -> bool:
        """True if this directory is inside a git repository (checks parents too)."""
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=self.root, capture_output=True, text=True, check=False,
        )
        return result.returncode == 0

    @cached_property
    def commit_count(self) -> int:
        if not self.is_git_repo:
            return 0
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=self.root, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            return 0
        return int(result.stdout.strip() or 0)

    @cached_property
    def detected_languages(self) -> list[str]:
        """Detect primary programming languages from manifests, then file extensions."""
        languages: set[str] = set()

        # Manifest-based detection (high confidence)
        manifest_signals: tuple[tuple[str, str], ...] = (
            ("pyproject.toml", "python"),
            ("setup.py", "python"),
            ("setup.cfg", "python"),
            ("Cargo.toml", "rust"),
            ("go.mod", "go"),
            ("Gemfile", "ruby"),
        )
        for filename, lang in manifest_signals:
            if (self.root / filename).is_file():
                languages.add(lang)

        # TypeScript takes priority over plain JavaScript
        if (self.root / "package.json").is_file():
            if (self.root / "tsconfig.json").is_file():
                languages.add("typescript")
            else:
                languages.add("javascript")

        # Extension-based fallback (only when manifest signals are absent)
        if not languages:
            ext_counts: dict[str, int] = {}
            for f in self._files[:500]:
                ext = f.suffix.lower()
                if ext == ".py":
                    ext_counts["python"] = ext_counts.get("python", 0) + 1
                elif ext in (".ts", ".tsx"):
                    ext_counts["typescript"] = ext_counts.get("typescript", 0) + 1
                elif ext in (".js", ".jsx", ".mjs"):
                    ext_counts["javascript"] = ext_counts.get("javascript", 0) + 1
                elif ext == ".go":
                    ext_counts["go"] = ext_counts.get("go", 0) + 1
                elif ext == ".rs":
                    ext_counts["rust"] = ext_counts.get("rust", 0) + 1
                elif ext == ".rb":
                    ext_counts["ruby"] = ext_counts.get("ruby", 0) + 1
            if ext_counts:
                languages.add(max(ext_counts, key=lambda k: ext_counts[k]))

        return sorted(languages)

    @cached_property
    def monorepo_tools(self) -> list[str]:
        """Detect monorepo tooling signals at the repo root.

        Covers four families:

        1. **JS ecosystem** — npm/yarn workspaces, lerna, pnpm, nx, rush,
           turborepo. These advertise themselves via dedicated files.
        2. **Python workspace declarations** — ``[tool.uv.workspace]``,
           ``[tool.rye.workspace]`` in ``pyproject.toml``. Modern Python
           monorepos opt in here.
        3. **Cargo / Gradle** — ``[workspace]`` in ``Cargo.toml``, and
           the presence of ``settings.gradle`` / ``settings.gradle.kts``.
        4. **Convention monorepos** — repos with ≥ 2 *direct child*
           directories that each carry their own manifest
           (``pyproject.toml`` / ``setup.py`` / ``Cargo.toml`` /
           ``package.json`` / ``go.mod`` / ``build.gradle`` /
           ``pom.xml``). This catches the very common pattern where a
           single git repo holds N sibling packages without declaring
           a formal workspace — e.g. enterprise Python monorepos that
           predate ``uv`` / ``rye`` and rely on a top-level build
           orchestrator (Earthfile / Bazel / Jenkinsfile).

           The ≥ 2 threshold keeps the false-positive rate low: a
           single ``examples/foo/setup.py`` next to the real package
           doesn't trip it. Only when the repo actually contains
           multiple independently-manifested siblings does the
           ``convention-monorepo`` label fire.
        """
        tools: list[str] = []

        pkg_json = self.root / "package.json"
        if pkg_json.is_file():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
                if "workspaces" in data:
                    tools.append("npm-workspaces")
            except (json.JSONDecodeError, OSError):
                pass

        for filename, label in (
            ("lerna.json", "lerna"),
            ("pnpm-workspace.yaml", "pnpm"),
            ("nx.json", "nx"),
            ("rush.json", "rush"),
            ("turbo.json", "turborepo"),
        ):
            if (self.root / filename).is_file():
                tools.append(label)

        pyproject = self.root / "pyproject.toml"
        if pyproject.is_file():
            body = self.read_text("pyproject.toml") or ""
            if "[tool.uv.workspace]" in body:
                tools.append("uv-workspace")
            if "[tool.rye.workspace]" in body:
                tools.append("rye-workspace")

        cargo = self.root / "Cargo.toml"
        if cargo.is_file():
            body = self.read_text("Cargo.toml") or ""
            if "[workspace]" in body:
                tools.append("cargo-workspace")

        if (
            (self.root / "settings.gradle").is_file()
            or (self.root / "settings.gradle.kts").is_file()
        ):
            tools.append("gradle-multi-project")

        # Convention monorepo: ≥ 2 direct-child manifest-bearing dirs.
        # Kept here (not in the tooling list above) because the bar is
        # structural: any repo whose layout *is* a monorepo, regardless
        # of which build tool stitches it together.
        if self._count_sibling_manifests() >= 2:
            tools.append("convention-monorepo")

        return tools

    def _count_sibling_manifests(self) -> int:
        """Count direct-child directories that carry their own manifest.

        Direct children only (depth-1) so a repo's ``examples/`` or
        ``tests/`` subtree can't accidentally inflate the count. The
        check is purely existence-based; we don't parse the manifests.
        """
        manifest_names = (
            "pyproject.toml", "setup.py", "Cargo.toml", "package.json",
            "go.mod", "build.gradle", "build.gradle.kts", "pom.xml",
        )
        count = 0
        try:
            for entry in self.root.iterdir():
                if entry.is_symlink() or not entry.is_dir():
                    continue
                if entry.name in _EXCLUDED_DIRS:
                    continue
                if any((entry / m).is_file() for m in manifest_names):
                    count += 1
        except OSError:
            return 0
        return count

    @cached_property
    def is_monorepo(self) -> bool:
        return len(self.monorepo_tools) > 0

    @cached_property
    def orientation_tokens(self) -> int:
        """Estimated tokens for an agent to orient in this repo (chars/4 heuristic).

        When an AGENTS.md (or CLAUDE.md) file is present, it is used as the
        primary orientation document instead of the README. Agent-targeted docs
        are intentionally concise; using the README for these repos overstates
        the real orientation cost an agent faces.
        """
        total_chars = 0
        # Prefer AGENTS.md / CLAUDE.md — concise agent-targeted orientation docs.
        # Fall back to README only when no agent doc is present.
        agent_doc_names = ("AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md")
        used_agent_doc = False
        for name in agent_doc_names:
            path = self.root / name
            if path.is_file():
                total_chars += len(self.read_text(name) or "")
                used_agent_doc = True
                break

        if not used_agent_doc:
            for name in ("README.md", "README.rst", "README.txt", "README"):
                f = self.has_file(name)
                if f:
                    total_chars += len(self.read_text(f) or "")
                    break
        # Primary manifest
        for m in ("pyproject.toml", "package.json", "Cargo.toml", "go.mod", "Gemfile"):
            if (self.root / m).is_file():
                total_chars += len(self.read_text(m) or "")
                break
        # Top-level source files (up to 5, by size descending)
        top_src = sorted(
            [
                f for f in self._files
                if len(f.parts) <= 2 and f.suffix in (".py", ".ts", ".js", ".go", ".rs")
            ],
            key=lambda p: (self.root / p).stat().st_size,
            reverse=True,
        )[:5]
        for f in top_src:
            total_chars += len(self.read_text(f) or "")
        return total_chars // 4
