"""Coordination pillar checks (workspace-level only).

These checks evaluate the workspace ROOT (and have access to its child
paths), not any individual child. They answer 'can a fleet of agents
operate coherently across these repos?' — the named failure mode in
the agentic-engineering literature is 'context drift' (Mabl) /
'context wall' (Augment, Faros).

v1 ships three checks:

- coordination.root_agents_md   — root has a non-empty AGENTS.md
- coordination.repos_manifest   — workspace declares its member repos
- coordination.dep_graph        — workspace declares dep / change order

See docs/superpowers/specs/2026-05-23-workspace-scan-coordination-pillar-design.md
"""
from __future__ import annotations

from pathlib import Path

from agent_readiness.models import (
    CheckResult,
    Finding,
    Pillar,
    Severity,
)

_AGENTS_MD_NAMES = ("AGENTS.md", "agents.md", "Agents.md")


def evaluate_coordination(root: Path, children: list[Path]) -> list[CheckResult]:
    """Run every v1 Coordination check; return their CheckResults."""
    return [
        check_root_agents_md(root, children),
        check_repos_manifest(root, children),
        check_dep_graph(root, children),
    ]


# --- coordination.root_agents_md ----------------------------------------

def check_root_agents_md(root: Path, children: list[Path]) -> CheckResult:
    """Workspace root has a non-empty AGENTS.md.

    The literature is unanimous (Mabl, Rafferty, Ricky, Bishoy, agents.md
    spec) that workspace-level orientation lives in a root AGENTS.md.
    Without it, agents have no portfolio-level context.
    """
    body = _read_first(root, _AGENTS_MD_NAMES)
    if body is None or not body.strip():
        finding = Finding(
            check_id="coordination.root_agents_md",
            pillar=Pillar.COORDINATION,
            message="Workspace root has no AGENTS.md (or it is empty).",
            severity=Severity.WARN,
            fix_hint=(
                "Agents need portfolio-level orientation when working across "
                "multiple repos. Create a root AGENTS.md that names the repos "
                "in this workspace and links to each child's own AGENTS.md."
            ),
            action={
                "kind": "create_file",
                "path": "AGENTS.md",
                "content": (
                    "# Workspace AGENTS.md\n\n"
                    "Portfolio-level orientation for agents. List the "
                    "member repos and link to each child's AGENTS.md.\n\n"
                    "## Repos in this workspace\n\n"
                    "<!-- enumerate child repos here -->\n\n"
                    "## Change order\n\n"
                    "<!-- document which repos depend on which -->\n"
                ),
            },
            verify={
                "command": "test -s AGENTS.md",
                "description": "Root AGENTS.md exists and is non-empty.",
            },
        )
        return CheckResult(
            check_id="coordination.root_agents_md",
            pillar=Pillar.COORDINATION,
            score=0.0,
            findings=[finding],
        )

    return _coordination_pass("coordination.root_agents_md")


# --- coordination.repos_manifest ----------------------------------------

def check_repos_manifest(root: Path, children: list[Path]) -> CheckResult:
    """Workspace declares its member repos somewhere agents can read.

    Passes if any of:

    - A workspace manifest exists (pnpm-workspace.yaml, repos.yaml,
      cargo workspace, go.work, package.json with workspaces, etc.)
    - Root AGENTS.md contains a section that names ≥ half of `children`.
    """
    if _has_workspace_manifest(root):
        return _coordination_pass("coordination.repos_manifest")
    if _agents_md_enumerates_children(root, children):
        return _coordination_pass("coordination.repos_manifest")

    listed = "\n".join(f"- `{c.name}`" for c in children)
    finding = Finding(
        check_id="coordination.repos_manifest",
        pillar=Pillar.COORDINATION,
        message=(
            f"Workspace has {len(children)} children but no manifest "
            f"declaring them (no pnpm-workspace.yaml / repos.yaml / "
            f"workspace package.json / root AGENTS.md enumeration)."
        ),
        severity=Severity.WARN,
        fix_hint=(
            "Either add a tool-specific workspace manifest (pnpm-workspace.yaml, "
            "cargo workspace, go.work, etc.), a generic repos.yaml, or list the "
            "repos under a '## Repos in this workspace' section in the root AGENTS.md."
        ),
        action={
            "kind": "append_to_file",
            "path": "AGENTS.md",
            "content": (
                "\n\n## Repos in this workspace\n\n"
                + listed
                + "\n"
            ),
        },
        verify={
            "command": "rg -q '## Repos in this workspace' AGENTS.md",
            "description": "Root AGENTS.md enumerates the member repos.",
        },
    )
    return CheckResult(
        check_id="coordination.repos_manifest",
        pillar=Pillar.COORDINATION,
        score=0.0,
        findings=[finding],
    )


# --- coordination.dep_graph ---------------------------------------------

def check_dep_graph(root: Path, children: list[Path]) -> CheckResult:
    """Workspace documents repo dependencies / change order.

    Passes if any of:

    - A ``WORKSPACE_GRAPH.md`` (or equivalent) file exists
    - Root AGENTS.md contains a section header matching change-order /
      dependency-graph language ('Change order', 'Dependency graph',
      'depends_on')
    - A workspace manifest with an explicit packages/members list exists
      (pnpm-workspace.yaml, package.json workspaces array, cargo
      [workspace] members, go.work use)
    """
    if (root / "WORKSPACE_GRAPH.md").exists():
        return _coordination_pass("coordination.dep_graph")
    if (root / "DEPENDENCY_GRAPH.md").exists():
        return _coordination_pass("coordination.dep_graph")

    body = _read_first(root, _AGENTS_MD_NAMES) or ""
    body_lower = body.lower()
    dep_signals = ("change order", "dependency graph", "depends_on", "depends on")
    if any(s in body_lower for s in dep_signals):
        return _coordination_pass("coordination.dep_graph")

    if _has_explicit_packages_manifest(root):
        return _coordination_pass("coordination.dep_graph")

    finding = Finding(
        check_id="coordination.dep_graph",
        pillar=Pillar.COORDINATION,
        message=(
            f"Workspace has no documented dependency / change order "
            f"({len(children)} children). Agents working across these "
            f"repos can't know which to change first."
        ),
        severity=Severity.WARN,
        fix_hint=(
            "Document repo dependencies and change order. The "
            "agentic-engineering literature (Mabl, Bishoy Labib) names "
            "this as the single most critical concept for multi-repo "
            "agent work. Either add a WORKSPACE_GRAPH.md or include a "
            "'## Change order' section in the root AGENTS.md."
        ),
        action={
            "kind": "append_to_file",
            "path": "AGENTS.md",
            "content": (
                "\n\n## Change order\n\n"
                "Document the order in which repos should be modified when "
                "making cross-cutting changes. Conventional order:\n\n"
                "1. Shared libraries first\n"
                "2. Backend services second\n"
                "3. Frontend applications last\n"
            ),
        },
        verify={
            "command": (
                "test -f WORKSPACE_GRAPH.md "
                "|| rg -q -i 'change order|dependency graph|depends_on' AGENTS.md"
            ),
            "description": "Workspace documents change order or dependency graph.",
        },
    )
    return CheckResult(
        check_id="coordination.dep_graph",
        pillar=Pillar.COORDINATION,
        score=0.0,
        findings=[finding],
    )


# --- helpers ------------------------------------------------------------

def _coordination_pass(check_id: str) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        pillar=Pillar.COORDINATION,
        score=100.0,
        findings=[],
    )


def _has_workspace_manifest(root: Path) -> bool:
    """True if any tool-specific or generic workspace declaration exists."""
    if (root / "pnpm-workspace.yaml").exists():
        return True
    if (root / "repos.yaml").exists() or (root / "repos.yml").exists():
        return True
    if (root / "go.work").exists():
        return True
    cargo = root / "Cargo.toml"
    if cargo.exists() and "[workspace]" in _safe_read(cargo):
        return True
    pkg = root / "package.json"
    if pkg.exists() and '"workspaces"' in _safe_read(pkg):
        return True
    pyproj = root / "pyproject.toml"
    if pyproj.exists():
        body = _safe_read(pyproj)
        if "[tool.uv.workspace]" in body or "[tool.rye.workspace]" in body:
            return True
    if (root / "settings.gradle").exists() or (root / "settings.gradle.kts").exists():
        return True
    return False


def _agents_md_enumerates_children(root: Path, children: list[Path]) -> bool:
    """True if root AGENTS.md names ≥ half of the children by directory name.

    Match is word-boundary anchored so short / common directory names
    (``a``, ``api``, ``cli``) don't false-positive against unrelated
    prose (e.g. ``a`` in ``workspace``).
    """
    import re

    body = _read_first(root, _AGENTS_MD_NAMES)
    if not body or not children:
        return False
    body_lower = body.lower()
    hits = 0
    for c in children:
        name = re.escape(c.name.lower())
        if re.search(rf"(?<![\w-]){name}(?![\w-])", body_lower):
            hits += 1
    return hits * 2 >= len(children)


def _has_explicit_packages_manifest(root: Path) -> bool:
    """A manifest that lists members counts as a dep graph.

    pnpm-workspace.yaml, package.json workspaces array, cargo
    [workspace] members, go.work use.
    """
    pnpm = root / "pnpm-workspace.yaml"
    if pnpm.exists() and "packages:" in _safe_read(pnpm):
        return True
    pkg = root / "package.json"
    if pkg.exists() and '"workspaces"' in _safe_read(pkg):
        return True
    cargo = root / "Cargo.toml"
    if cargo.exists():
        body = _safe_read(cargo)
        if "[workspace]" in body and "members" in body:
            return True
    gowork = root / "go.work"
    if gowork.exists() and "use " in _safe_read(gowork):
        return True
    return False


def _read_first(root: Path, names: tuple[str, ...]) -> str | None:
    for name in names:
        p = root / name
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
    return None


def _safe_read(p: Path, max_bytes: int = 64_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except (OSError, UnicodeDecodeError):
        return ""
