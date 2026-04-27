"""RepoContext: cached, read-only view of a repository for checks to consume.

Built once per scan; checks should pull from this rather than re-walking the tree.
"""

from __future__ import annotations

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
    def orientation_tokens(self) -> int:
        """Estimated tokens for an agent to orient in this repo (chars/4 heuristic)."""
        total_chars = 0
        # README(s)
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
