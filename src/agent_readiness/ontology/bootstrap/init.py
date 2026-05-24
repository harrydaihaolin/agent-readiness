"""bootstrap.init — scaffold an empty ontology/ skeleton from a template.

Refuses to overwrite. Honors profile (`workspace` / `single-repo` / `monorepo`).
Returns a typed report of files written.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_TEMPLATE = Path(
    "/Users/haolin.dai/Documents/agent-readiness_project/agent-readiness-manifest/exemplar/ontology"
)

_PROFILE_SKIPS: dict[str, set[str]] = {
    "workspace": set(),
    "single-repo": {
        "Protocol.yaml",
        "RulesPack.yaml",
        "Release.yaml",
        "vendors.yaml",
        "providesProtocol.yaml",
        "consumesProtocol.yaml",
        "releasedAs.yaml",
    },
    "monorepo": {
        "vendors.yaml",
        "providesProtocol.yaml",
        "consumesProtocol.yaml",
    },
}


@dataclass
class InitReport:
    files_written: int
    profile: str
    skipped_due_to_profile: list[str] = field(default_factory=list)


def init_ontology(
    target: Path,
    profile: str = "workspace",
    manifest_template: Path | None = None,
) -> InitReport:
    """Scaffold an ontology/ skeleton under `target` from `manifest_template`.

    - `profile` controls which type files are skipped.
    - Refuses to overwrite existing files; raises FileExistsError.
    - Returns an InitReport describing what was written.
    """
    if profile not in _PROFILE_SKIPS:
        raise ValueError(
            f"Unknown profile: {profile!r}. Valid: {sorted(_PROFILE_SKIPS)}"
        )

    template = manifest_template or _DEFAULT_TEMPLATE
    if not template.is_dir():
        raise FileNotFoundError(
            f"Template not found: {template}. Pass manifest_template= explicitly."
        )

    skips = _PROFILE_SKIPS[profile]
    target_ontology = target / "ontology"
    written = 0
    skipped: list[str] = []

    for src in sorted(template.rglob("*.yaml")):
        rel = src.relative_to(template)
        if rel.name in skips:
            skipped.append(str(rel))
            continue
        dst = target_ontology / rel
        if dst.exists():
            raise FileExistsError(f"Refusing to overwrite {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written += 1

    # Also copy README if present in template
    template_readme = template / "README.md"
    if template_readme.is_file():
        dst_readme = target_ontology / "README.md"
        if not dst_readme.exists():
            dst_readme.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template_readme, dst_readme)
            written += 1

    # Always-empty dirs with .gitkeep
    for empty in ("instances", "intents", "actionTypes", "intentTypes"):
        d = target_ontology / empty
        d.mkdir(parents=True, exist_ok=True)
        gitkeep = d / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    return InitReport(
        files_written=written,
        profile=profile,
        skipped_due_to_profile=skipped,
    )
