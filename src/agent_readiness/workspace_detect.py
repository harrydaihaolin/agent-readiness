"""Workspace detection.

Classifies a user-supplied path as one of:

* ``single_repo``           — one git repo, scan as today.
* ``monorepo``              — one git repo with multiple internal workspaces
  (pnpm/yarn/npm workspaces, Cargo workspace, Bazel, Go work, Mix umbrella,
  Maven/Gradle multi-module, etc.); v1 still scans it as one repo.
* ``multi_repo_workspace``  — parent dir containing N sibling git repos;
  ``agent-readiness scan`` exits non-zero here and emits a structured
  error pointing at ``agent-readiness detect``.

The detector is the single source of truth — the CLI, the MCP server, and
any edge client (action, vscode, gh-extension) all call ``detect(path)``
rather than re-deriving the classification.

The algorithm is the design-spec heuristic; downstream consumers should
treat the result envelope as a wire format and check ``version`` before
parsing. The empirical validation against >=1000 public repos is tracked
as a separate research task; until that lands the detector ships under
the internal label ``detect_v1`` so the algorithm can rev without
breaking the wire format.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DETECT_VERSION = "detect_v1"

# ---------- constants used by both step-1 (in-repo) and step-2/3 logic --

# Directory names that are never an inner workspace / nested repo. Used
# to skip child traversal in step 2/3 and to drop noise findings when
# scoring "manifest density" in step 1's Signal C.
_PRUNE_DIR_NAMES: frozenset[str] = frozenset({
    "examples", "example", "__fixtures__",
    "node_modules", "vendor", "target",
    "dist", "build", ".venv", "venv",
})

# Path *segments* under the root that contain fixtures / examples and
# should not contribute manifests toward Signal C. Matched against the
# relative path with normalised separators (so ``tests/fixtures/foo``
# matches regardless of platform).
_PRUNE_PATH_SEGMENTS: tuple[str, ...] = (
    "tests/fixtures/", "test/fixtures/", "__fixtures__/",
)

# Manifest file names we count toward Signal C (manifest density) and
# toward Signal B's "convention dir + child manifests" rule.
_MANIFEST_FILES: frozenset[str] = frozenset({
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "mix.exs",
    "Gemfile",
    "composer.json",
    "build.sbt",
})

# Conventional monorepo workspace dir names. Listed in declaration order
# of "most common first" so the matched signal name is stable across runs.
_CONVENTION_DIRS: tuple[str, ...] = (
    "packages", "apps", "services", "libs", "modules", "crates", "cmd",
)


# ---------- dataclasses --------------------------------------------------


@dataclass(slots=True)
class DetectedRepo:
    """One repository the detector found inside the workspace.

    ``name``      is the directory basename (or the supplied root's
                  basename for single-repo classifications).
    ``rel_path``  is always ``./<name>`` for child repos and ``./`` for
                  the root; consumers display this so the user sees the
                  same string the AGENTS.md table uses.
    ``has_git``   is False only in the no-git fallback (step 3).
    ``display_name`` and ``description`` come from AGENTS.md enrichment
    and are ``None`` when the repo is not listed in AGENTS.md.
    """

    name: str
    path: str
    rel_path: str
    has_git: bool = True
    display_name: str | None = None
    description: str | None = None


@dataclass(slots=True)
class DriftWarning:
    """One inconsistency between AGENTS.md and what's on disk.

    Two kinds:

    * ``missing_from_disk``   — AGENTS.md mentions a repo that has no
                                ``.git`` checkout.
    * ``missing_from_agents`` — a checkout exists on disk that AGENTS.md
                                doesn't list.
    """

    kind: str
    agents_md_path: str | None
    detected_path: str | None
    message: str


@dataclass(slots=True)
class WorkspaceDetection:
    """The full ``detect`` envelope. Wire-stable; bump ``version`` to evolve."""

    classification: str
    confidence: str
    root: str
    repos: list[DetectedRepo] = field(default_factory=list)
    drift_warnings: list[DriftWarning] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    version: str = DETECT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "classification": self.classification,
            "confidence": self.confidence,
            "root": self.root,
            "repos": [asdict(r) for r in self.repos],
            "drift_warnings": [asdict(w) for w in self.drift_warnings],
            "signals": self.signals,
        }


# ---------- helpers -----------------------------------------------------


def _is_repo_dir(p: Path) -> bool:
    """A path is a non-bare git repo if it contains a ``.git`` entry.

    Handles three cases the spec calls out:

    * Regular ``.git/`` directory.
    * ``.git`` file pointing to a worktree gitdir.
    * ``.git`` file pointing into a parent's gitdir (submodule); we
      still count this as a separate repo per spec.

    Bare repos (``HEAD`` + ``objects/`` at the top level) are ignored.
    """
    git = p / ".git"
    if git.is_dir():
        return True
    if git.is_file():
        return True
    return False


def _safe_read_text(p: Path, max_bytes: int = 256_000) -> str:
    try:
        with p.open("rb") as fh:
            data = fh.read(max_bytes)
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def _has_substr(p: Path, needle: str, max_bytes: int = 64_000) -> bool:
    """Quick substring probe over the first N bytes of a file."""
    text = _safe_read_text(p, max_bytes=max_bytes)
    return needle in text


def _has_pkg_json_workspaces(root: Path) -> bool:
    pkg = root / "package.json"
    if not pkg.is_file():
        return False
    try:
        data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return False
    return "workspaces" in data


def _has_cargo_workspace(root: Path) -> bool:
    cargo = root / "Cargo.toml"
    if not cargo.is_file():
        return False
    return _has_substr(cargo, "[workspace]")


def _has_pyproject_workspace(root: Path) -> bool:
    pp = root / "pyproject.toml"
    if not pp.is_file():
        return False
    text = _safe_read_text(pp)
    return (
        "[tool.uv.workspace]" in text
        or "[tool.rye.workspace]" in text
        # Poetry's `packages` table is workspace-ish but also fires on
        # plain libraries that ship multiple modules. Require the
        # explicit `[tool.poetry]` section AND a `packages` array.
        or ("[tool.poetry]" in text and re.search(r"^\s*packages\s*=", text, re.M) is not None)
    )


def _has_gradle_multi(root: Path) -> bool:
    for fname in ("settings.gradle", "settings.gradle.kts"):
        f = root / fname
        if f.is_file() and re.search(r"^\s*include\b", _safe_read_text(f), re.M):
            return True
    return False


def _has_maven_modules(root: Path) -> bool:
    pom = root / "pom.xml"
    if not pom.is_file():
        return False
    text = _safe_read_text(pom)
    return "<modules>" in text


def _has_mix_umbrella(root: Path) -> bool:
    mx = root / "mix.exs"
    if not mx.is_file():
        return False
    return "apps_path:" in _safe_read_text(mx)


def _signal_a(root: Path) -> tuple[bool, list[str], list[str]]:
    """Signal A — explicit workspace declaration (confidence high).

    Returns (fired, fired_labels, matched_paths). Labels are stable
    machine-readable tokens (e.g. ``"A:pnpm-workspace.yaml"``).
    """
    fired: list[str] = []
    matched: list[str] = []

    # File-existence-only checks (cheap, no read).
    for fname in (
        "pnpm-workspace.yaml",
        "nx.json", "turbo.json", "lerna.json", "rush.json",
        "go.work",
        "WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel",
        "pants.toml", ".buckconfig",
    ):
        if (root / fname).is_file():
            fired.append(f"A:{fname}")
            matched.append(fname)

    # File-existence + small content probe.
    if _has_pkg_json_workspaces(root):
        fired.append("A:package.json#workspaces")
        matched.append("package.json")
    if _has_cargo_workspace(root):
        fired.append("A:Cargo.toml#workspace")
        matched.append("Cargo.toml")
    if _has_pyproject_workspace(root):
        fired.append("A:pyproject.toml#workspace")
        matched.append("pyproject.toml")
    if _has_gradle_multi(root):
        # Use the first one that exists so the label is determinate.
        for fname in ("settings.gradle", "settings.gradle.kts"):
            if (root / fname).is_file():
                fired.append(f"A:{fname}#include")
                matched.append(fname)
                break
    if _has_maven_modules(root):
        fired.append("A:pom.xml#modules")
        matched.append("pom.xml")
    if _has_mix_umbrella(root):
        fired.append("A:mix.exs#apps_path")
        matched.append("mix.exs")

    return (len(fired) > 0, fired, matched)


def _signal_b(root: Path) -> tuple[bool, list[str], list[str]]:
    """Signal B — convention dir + >=2 child manifests (confidence medium)."""
    fired: list[str] = []
    matched: list[str] = []
    for d in _CONVENTION_DIRS:
        sub = root / d
        if not sub.is_dir():
            continue
        # Count immediate children with at least one manifest.
        children_with_manifest = 0
        for child in _safe_iterdir(sub):
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            if any((child / m).is_file() for m in _MANIFEST_FILES):
                children_with_manifest += 1
                if children_with_manifest >= 2:
                    break
        if children_with_manifest >= 2:
            fired.append(f"B:{d}/")
            matched.append(f"{d}/")
    return (len(fired) > 0, fired, matched)


def _signal_c(root: Path) -> tuple[bool, list[str], list[str]]:
    """Signal C — >=3 manifests under non-ignored paths (confidence low)."""
    count = 0
    matched: list[str] = []
    for path in _walk_manifests(root):
        rel = path.relative_to(root).as_posix()
        matched.append(rel)
        count += 1
        if count >= 8:
            break  # bound work; 3 is enough to fire, we collect a few for evidence
    fired = count >= 3
    return (fired, ["C:manifest_density"] if fired else [], matched)


def _walk_manifests(root: Path, *, max_files: int = 5000) -> list[Path]:
    """Walk the tree once and return manifests under non-ignored paths.

    Capped at ``max_files`` so a pathological monorepo can't make us
    scan forever. The cap is well above the 3-manifest threshold so it
    never changes the classification result; it just bounds runtime.
    """
    out: list[Path] = []
    seen = 0
    for dirpath, dirnames, filenames in _safe_walk(root):
        # In-place mutation of dirnames prunes the walk.
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and d not in _PRUNE_DIR_NAMES
        ]
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        elif rel_dir and any(
            (rel_dir + "/").startswith(seg) or ("/" + rel_dir + "/").find("/" + seg) != -1
            for seg in _PRUNE_PATH_SEGMENTS
        ):
            # Drop everything under fixtures dirs.
            continue
        for name in filenames:
            if name in _MANIFEST_FILES:
                out.append(Path(dirpath) / name)
                seen += 1
                if seen >= max_files:
                    return out
    return out


def _safe_walk(root: Path):
    """``os.walk`` that won't explode on a perm-denied subdir."""
    import os
    try:
        yield from os.walk(root, followlinks=False)
    except OSError:
        return


def _safe_iterdir(p: Path) -> list[Path]:
    try:
        return list(p.iterdir())
    except OSError:
        return []


# ---------- AGENTS.md enrichment ---------------------------------------


_AGENTS_MD_ROW_RE = re.compile(
    # `| [`name`](./relpath) | display | ... |`  — accept variants:
    #   - relpath: `./foo` or `foo/`
    #   - link wrapper optional (`[`foo`](./foo)` or just `./foo`).
    r"^\s*\|\s*"
    r"(?:\[\s*`?(?P<labelled>[\w.\-/]+)`?\s*\]\s*\(\s*(?P<linked>[\w./\-]+)\s*\)"
    r"|`?(?P<bare>\./[\w.\-/]+|[\w.\-]+/?)`?)"
    r"\s*\|"
    r"(?P<rest>.*)$"
)


def _parse_agents_md(root: Path) -> dict[str, dict[str, str | None]]:
    """Parse the root AGENTS.md for repo-table rows.

    Returns a dict keyed by repo basename. Each value has
    ``display_name`` (the 2nd column, trimmed of markdown) and
    ``description`` (the 3rd column if present, else ``None``).

    AGENTS.md is enrichment, not source of truth — failure to parse
    yields ``{}`` and the caller keeps the heuristic classification.
    """
    p = root / "AGENTS.md"
    if not p.is_file():
        return {}
    text = _safe_read_text(p, max_bytes=256_000)
    out: dict[str, dict[str, str | None]] = {}
    in_table = False
    for line in text.splitlines():
        # A markdown separator row signals we're inside a table now.
        if re.match(r"^\s*\|\s*[:\-\s|]+\s*\|", line):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.lstrip().startswith("|"):
            in_table = False
            continue
        m = _AGENTS_MD_ROW_RE.match(line)
        if not m:
            continue
        name: str | None = None
        if m.group("linked"):
            link = m.group("linked").strip()
            name = link.lstrip("./").rstrip("/")
        elif m.group("bare"):
            bare = m.group("bare").strip()
            name = bare.lstrip("./").rstrip("/")
        if not name or "/" in name:
            # We only enrich top-level entries; nested paths
            # (e.g. "./apps/foo") aren't part of the multi-repo
            # classification.
            continue
        rest = m.group("rest")
        cols = [c.strip() for c in rest.split("|") if c.strip() != ""]
        display = cols[0] if len(cols) >= 1 else None
        # The third column in this project's AGENTS.md is "Lang/stack";
        # not a description per se but useful enough to surface. The
        # parser doesn't try to be clever — it just hands the column
        # along as ``description``.
        description = cols[1] if len(cols) >= 2 else None
        # Strip backticks for cleaner narration.
        if display:
            display = display.strip("`").strip()
        if description:
            description = description.strip("`").strip()
        out[name] = {"display_name": display, "description": description}
    return out


# ---------- main entry point -------------------------------------------


def detect(path: Path) -> WorkspaceDetection:
    """Classify ``path`` and return the full envelope.

    The classification is conservative: when in doubt we prefer
    ``single_repo`` over ``monorepo`` (so the scanner still runs) and
    ``multi_repo_workspace`` is only declared when we see hard evidence
    (>=2 child ``.git`` entries in step 2, or the no-git fallback's
    ``medium`` signal in step 3).
    """
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"detect path is not a directory: {root}")

    root_has_git = _is_repo_dir(root)

    # ---- Step 1: root is a repo --------------------------------------
    if root_has_git:
        a_fire, a_lbl, a_paths = _signal_a(root)
        b_fire, b_lbl, b_paths = _signal_b(root)
        c_fire, c_lbl, c_paths = _signal_c(root)

        all_lbl = a_lbl + b_lbl + c_lbl
        all_paths = a_paths + b_paths + c_paths

        if a_fire or b_fire or c_fire:
            confidence = "high" if a_fire else ("medium" if b_fire else "low")
            return _single_repo_envelope(
                root,
                classification="monorepo",
                confidence=confidence,
                fired=all_lbl,
                matched_paths=all_paths,
            )

        return _single_repo_envelope(
            root,
            classification="single_repo",
            confidence="high",
            fired=[],
            matched_paths=[],
        )

    # ---- Step 2: walk one level for child .git/ -----------------------
    children_with_git = _enumerate_child_repos(root)

    if len(children_with_git) >= 2:
        return _multi_repo_envelope(
            root,
            child_repos=children_with_git,
            confidence="high",
            fired=["step2:child_git>=2"],
            matched_paths=[f"./{c.name}/.git" for c in children_with_git],
        )
    if len(children_with_git) == 1:
        # Single nested repo — return *that child* as the canonical
        # scan target (per spec: "return that child's path").
        only = children_with_git[0]
        return WorkspaceDetection(
            classification="single_repo",
            confidence="high",
            root=str(only),
            repos=[DetectedRepo(
                name=only.name,
                path=str(only),
                rel_path=f"./{only.name}",
                has_git=True,
            )],
            signals={
                "fired": ["step2:single_child_repo"],
                "matched_paths": [f"./{only.name}/.git"],
                "version": DETECT_VERSION,
            },
        )

    # ---- Step 3: no .git anywhere — re-run signals A/B/C on the root, --
    # then fall back to the manifest-based fan-out used by step 2.
    # Spec: "same logic as steps 1 + 2 but using manifests instead of
    # .git entries." So a tarball-unzipped pnpm workspace still
    # classifies as `monorepo` (Signal A) even without a checked-out
    # .git/.
    a_fire, a_lbl, a_paths = _signal_a(root)
    b_fire, b_lbl, b_paths = _signal_b(root)
    c_fire, c_lbl, c_paths = _signal_c(root)

    if a_fire or b_fire or c_fire:
        all_lbl = a_lbl + b_lbl + c_lbl
        all_paths = a_paths + b_paths + c_paths
        confidence = "high" if a_fire else ("medium" if b_fire else "low")
        return _single_repo_envelope(
            root,
            classification="monorepo",
            confidence=confidence,
            fired=all_lbl,
            matched_paths=all_paths,
        )

    children_with_manifest = _enumerate_child_manifests(root)
    if len(children_with_manifest) >= 2:
        return _multi_repo_envelope(
            root,
            child_repos=children_with_manifest,
            confidence="medium",
            fired=["step3:child_manifests>=2"],
            matched_paths=[f"./{c.name}/" for c in children_with_manifest],
            has_git=False,
        )

    # No repo, no manifest fan-out. Treat as a single (gitless) repo so
    # the scanner can still try to score it.
    return WorkspaceDetection(
        classification="single_repo",
        confidence="low",
        root=str(root),
        repos=[DetectedRepo(
            name=root.name,
            path=str(root),
            rel_path="./",
            has_git=False,
        )],
        signals={
            "fired": ["step3:no_evidence"],
            "matched_paths": [],
            "version": DETECT_VERSION,
        },
    )


def _enumerate_child_repos(root: Path) -> list[Path]:
    out: list[Path] = []
    for c in sorted(_safe_iterdir(root)):
        if not c.is_dir():
            continue
        if c.name.startswith("."):
            continue
        if c.name in _PRUNE_DIR_NAMES:
            continue
        if _is_repo_dir(c):
            out.append(c)
    return out


def _enumerate_child_manifests(root: Path) -> list[Path]:
    out: list[Path] = []
    for c in sorted(_safe_iterdir(root)):
        if not c.is_dir():
            continue
        if c.name.startswith("."):
            continue
        if c.name in _PRUNE_DIR_NAMES:
            continue
        if any((c / m).is_file() for m in _MANIFEST_FILES):
            out.append(c)
    return out


def _single_repo_envelope(
    root: Path,
    *,
    classification: str,
    confidence: str,
    fired: list[str],
    matched_paths: list[str],
) -> WorkspaceDetection:
    return WorkspaceDetection(
        classification=classification,
        confidence=confidence,
        root=str(root),
        repos=[DetectedRepo(
            name=root.name,
            path=str(root),
            rel_path="./",
            has_git=_is_repo_dir(root),
        )],
        signals={
            "fired": fired,
            "matched_paths": matched_paths,
            "version": DETECT_VERSION,
        },
    )


def _multi_repo_envelope(
    root: Path,
    *,
    child_repos: list[Path],
    confidence: str,
    fired: list[str],
    matched_paths: list[str],
    has_git: bool = True,
) -> WorkspaceDetection:
    has_agents_md = (root / "AGENTS.md").is_file()
    agents_index = _parse_agents_md(root) if has_agents_md else {}
    seen_on_disk: set[str] = set()
    repos: list[DetectedRepo] = []
    for c in child_repos:
        meta = agents_index.get(c.name, {})
        repos.append(DetectedRepo(
            name=c.name,
            path=str(c),
            rel_path=f"./{c.name}",
            has_git=has_git and _is_repo_dir(c),
            display_name=meta.get("display_name"),
            description=meta.get("description"),
        ))
        seen_on_disk.add(c.name)

    # Drift only makes sense when there's an AGENTS.md to compare to.
    # Without one, "missing_from_agents" would fire on every detected
    # repo and drown the user in noise.
    drift: list[DriftWarning] = []
    if has_agents_md:
        for listed_name in agents_index:
            if listed_name in seen_on_disk:
                continue
            agents_md_path = f"./{listed_name}"
            if not (root / listed_name).exists():
                drift.append(DriftWarning(
                    kind="missing_from_disk",
                    agents_md_path=agents_md_path,
                    detected_path=None,
                    message=f"AGENTS.md lists {agents_md_path} but no .git found",
                ))
        for c in child_repos:
            if c.name not in agents_index:
                drift.append(DriftWarning(
                    kind="missing_from_agents",
                    agents_md_path=None,
                    detected_path=f"./{c.name}",
                    message=f"./{c.name} is on disk but AGENTS.md does not list it",
                ))

    return WorkspaceDetection(
        classification="multi_repo_workspace",
        confidence=confidence,
        root=str(root),
        repos=repos,
        drift_warnings=drift,
        signals={
            "fired": fired,
            "matched_paths": matched_paths,
            "version": DETECT_VERSION,
        },
    )


__all__ = [
    "DETECT_VERSION",
    "DetectedRepo",
    "DriftWarning",
    "WorkspaceDetection",
    "detect",
]
