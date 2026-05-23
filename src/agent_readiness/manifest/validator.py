"""Validate a loaded manifest beyond schema-only checks.

The Pydantic models in `agent_readiness_insights_protocol` enforce
schema correctness. This validator adds the *semantic* checks that
cross multiple files (tags-used-must-be-declared, arch-rule-id-must-
match-filename, etc.) and emits a uniform `ValidationResult` whose
JSON envelope is the contract for the CLI and MCP layers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .loader import LoadedManifest, ManifestLoadError, load_manifest_dir


Severity = Literal["error", "warn", "info"]


@dataclass(frozen=True)
class ValidationIssue:
    severity: Severity
    message: str
    location: str


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    api_version: str = "agent-readiness.io/v1"
    manifest_name: str = ""

    def to_json_envelope(self) -> dict:
        n_err  = sum(1 for i in self.issues if i.severity == "error")
        n_warn = sum(1 for i in self.issues if i.severity == "warn")
        n_info = sum(1 for i in self.issues if i.severity == "info")
        return {
            "apiVersion": self.api_version,
            "kind": "ManifestValidationResult",
            "summary": {
                "valid": self.valid,
                "manifest_name": self.manifest_name,
                "errors":   n_err,
                "warnings": n_warn,
                "infos":    n_info,
            },
            "issues": [
                {
                    "severity": i.severity,
                    "message":  i.message,
                    "location": i.location,
                }
                for i in self.issues
            ],
        }


def _check_tags_declared(
    loaded: LoadedManifest, issues: list[ValidationIssue],
) -> None:
    """Every tag axis referenced in boundary rules must be declared in
    `boundaries.spec.tagAxes`. Bare `default` (no `from`/`to`) is exempt.
    """
    declared = set(loaded.boundaries.spec.tagAxes.keys())
    src = (
        str(loaded.source_dir / "boundaries.yaml")
        if loaded.source_dir else "boundaries.yaml"
    )
    for rule in loaded.boundaries.spec.rules:
        for selector in (rule.from_ or {}, rule.to or {}):
            for axis in selector:
                if axis not in declared:
                    issues.append(ValidationIssue(
                        severity="error",
                        message=(
                            f"boundary rule '{rule.name}' references undeclared "
                            f"tag axis '{axis}' (declared axes: "
                            f"{sorted(declared) or '[]'})"
                        ),
                        location=src,
                    ))


def _check_arch_rule_filename_id_match(
    loaded: LoadedManifest, issues: list[ValidationIssue],
) -> None:
    """For each `rules/<filename>.yaml`, the file's `metadata.id` must
    start with the same numeric prefix as `<filename>` (e.g. file
    `001-foo.yaml` must declare an id like `001-foo`, `001-bar`, ...).
    """
    if loaded.source_dir is None:
        return
    rules_dir = loaded.source_dir / "rules"
    if not rules_dir.is_dir():
        return

    yaml_files = sorted(
        p for p in rules_dir.iterdir()
        if p.suffix in (".yaml", ".yml") and p.is_file()
    )
    if len(yaml_files) != len(loaded.arch_rules):
        # Loader skipped something; bail rather than guess at pairings.
        return

    for path, rule in zip(yaml_files, loaded.arch_rules):
        stem = path.stem
        file_prefix = stem.split("-", 1)[0]
        rule_prefix = rule.metadata.id.split("-", 1)[0]
        if file_prefix != rule_prefix:
            issues.append(ValidationIssue(
                severity="error",
                message=(
                    f"arch rule id '{rule.metadata.id}' does not match "
                    f"filename prefix '{file_prefix}'"
                ),
                location=str(path),
            ))


def validate_manifest_dir(root: Path) -> ValidationResult:
    """Top-level validator. Surfaces load errors AND semantic-check
    failures as a uniform list of `ValidationIssue` rows.
    """
    issues: list[ValidationIssue] = []
    try:
        loaded = load_manifest_dir(root)
    except ManifestLoadError as e:
        issues.append(ValidationIssue(
            severity="error",
            message=str(e),
            location=e.location or str(root),
        ))
        return ValidationResult(valid=False, issues=issues, manifest_name="")

    _check_tags_declared(loaded, issues)
    _check_arch_rule_filename_id_match(loaded, issues)

    valid = not any(i.severity == "error" for i in issues)
    return ValidationResult(
        valid=valid,
        issues=issues,
        manifest_name=loaded.manifest.metadata.name,
    )
