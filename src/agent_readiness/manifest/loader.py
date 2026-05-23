"""Load and parse an agent-readiness manifest directory into typed models.

The standard directory layout is:

    manifest.yaml                 # WorkspaceManifest
    glossary.yaml                 # Glossary
    boundaries.yaml               # Boundaries
    rules/*.yaml                  # ArchRule (zero or more, lex-sorted)
    .agent-readiness-version      # optional scanner constraint pin

`load_manifest_dir(root)` returns a frozen `LoadedManifest` (all four
typed models + the version constraint string). It raises
`ManifestLoadError` on any failure (missing required file, YAML parse
error, or Pydantic schema violation) — always with `location` populated
so the CLI / MCP layers can surface file context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from agent_readiness_insights_protocol.models import (
    ArchRule,
    Boundaries,
    Glossary,
    WorkspaceManifest,
)


class ManifestLoadError(Exception):
    """Raised when a manifest directory cannot be loaded.

    Wraps a Pydantic ValidationError or yaml.YAMLError with file
    context (`location`) so downstream renderers can show file:line
    instead of an opaque stack trace.
    """

    def __init__(
        self,
        message: str,
        location: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.location = location
        self.cause = cause


@dataclass(frozen=True)
class LoadedManifest:
    """A loaded, schema-validated manifest directory."""

    manifest: WorkspaceManifest
    glossary: Glossary
    boundaries: Boundaries
    arch_rules: list[ArchRule] = field(default_factory=list)
    scanner_version_constraint: str = ""
    source_dir: Path | None = None


_REQUIRED_FILES: tuple[tuple[str, type], ...] = (
    ("manifest.yaml",   WorkspaceManifest),
    ("glossary.yaml",   Glossary),
    ("boundaries.yaml", Boundaries),
)


def _load_yaml(path: Path) -> dict:
    try:
        text = path.read_text()
    except FileNotFoundError as e:
        raise ManifestLoadError(
            f"required file missing: {path.name}",
            location=str(path),
            cause=e,
        ) from e
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ManifestLoadError(
            f"YAML parse failed in {path.name}: {e}",
            location=str(path),
            cause=e,
        ) from e


def _validate(data: dict, cls: type, path: Path):
    try:
        return cls.model_validate(data)
    except ValidationError as e:
        raise ManifestLoadError(
            f"schema violation in {path.name}: {e.error_count()} error(s)",
            location=str(path),
            cause=e,
        ) from e


def _load_arch_rules(rules_dir: Path) -> list[ArchRule]:
    if not rules_dir.is_dir():
        return []
    rules: list[ArchRule] = []
    yaml_files = sorted(
        p for p in rules_dir.iterdir()
        if p.suffix in (".yaml", ".yml") and p.is_file()
    )
    for path in yaml_files:
        data = _load_yaml(path)
        rule = _validate(data, ArchRule, path)
        rules.append(rule)
    return rules


def _load_scanner_constraint(root: Path) -> str:
    pin = root / ".agent-readiness-version"
    if not pin.exists():
        return ""
    return pin.read_text().strip()


def load_manifest_dir(root: Path) -> LoadedManifest:
    """Load a manifest directory; raises `ManifestLoadError` on any failure."""
    root = Path(root)
    if not root.is_dir():
        raise ManifestLoadError(
            f"not a directory: {root}", location=str(root),
        )

    loaded: dict[str, object] = {}
    for name, cls in _REQUIRED_FILES:
        path = root / name
        if not path.exists():
            raise ManifestLoadError(
                f"required file missing: {name}",
                location=str(root),
            )
        data = _load_yaml(path)
        loaded[name] = _validate(data, cls, path)

    arch_rules = _load_arch_rules(root / "rules")

    return LoadedManifest(
        manifest=loaded["manifest.yaml"],     # type: ignore[arg-type]
        glossary=loaded["glossary.yaml"],     # type: ignore[arg-type]
        boundaries=loaded["boundaries.yaml"], # type: ignore[arg-type]
        arch_rules=arch_rules,
        scanner_version_constraint=_load_scanner_constraint(root),
        source_dir=root,
    )
