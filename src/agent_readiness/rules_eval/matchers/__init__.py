"""OSS and ontology matcher registry."""

from __future__ import annotations

from ._builtins import (
    MatcherFn,
    match_command_in_makefile,
    match_composite,
    match_file_size,
    match_manifest_field,
    match_path_glob,
    match_regex_in_files,
)
from .ontology_instance_count import match_ontology_instance_count
from .ontology_interface_satisfaction import match_ontology_interface_satisfaction
from .ontology_ref_closure import match_ontology_ref_closure

OssMatchTypeRegistry: dict[str, MatcherFn] = {
    "command_in_makefile": match_command_in_makefile,
    "composite": match_composite,
    "file_size": match_file_size,
    "manifest_field": match_manifest_field,
    "ontology_instance_count": match_ontology_instance_count,
    "ontology_interface_satisfaction": match_ontology_interface_satisfaction,
    "ontology_ref_closure": match_ontology_ref_closure,
    "path_glob": match_path_glob,
    "regex_in_files": match_regex_in_files,
}

__all__ = [
    "MatcherFn",
    "OssMatchTypeRegistry",
    "match_command_in_makefile",
    "match_composite",
    "match_file_size",
    "match_manifest_field",
    "match_ontology_instance_count",
    "match_ontology_interface_satisfaction",
    "match_ontology_ref_closure",
    "match_path_glob",
    "match_regex_in_files",
]
