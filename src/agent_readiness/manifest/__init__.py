"""Manifest loading and validation for the workspace-starter bible.

Re-exports the public surface so consumers can write
`from agent_readiness.manifest import validate_manifest_dir`.
"""
from .loader import LoadedManifest, ManifestLoadError, load_manifest_dir
from .validator import (
    ValidationIssue,
    ValidationResult,
    validate_manifest_dir,
)

__all__ = [
    "LoadedManifest",
    "ManifestLoadError",
    "ValidationIssue",
    "ValidationResult",
    "load_manifest_dir",
    "validate_manifest_dir",
]
