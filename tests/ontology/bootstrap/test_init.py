from __future__ import annotations

from pathlib import Path

import pytest

from agent_readiness.ontology.bootstrap.init import InitReport, init_ontology

from agent_readiness.ontology.bootstrap.init import _BUNDLED_TEMPLATE

MANIFEST_TEMPLATE = _BUNDLED_TEMPLATE


def test_init_creates_skeleton_in_empty_workspace(tmp_path: Path):
    report = init_ontology(
        tmp_path, profile="workspace", manifest_template=MANIFEST_TEMPLATE
    )
    assert isinstance(report, InitReport)
    assert (tmp_path / "ontology" / "objectTypes" / "Repo.yaml").exists()
    assert (tmp_path / "ontology" / "linkTypes" / "dependsOn.yaml").exists()
    assert (tmp_path / "ontology" / "interfaces" / "Releasable.yaml").exists()
    assert (tmp_path / "ontology" / "functions" / "compute_publish_order.yaml").exists()
    # 8 + 8 + 6 + 3 = 25 type files minimum
    assert report.files_written >= 25
    assert report.profile == "workspace"
    assert report.skipped_due_to_profile == []
    # always-empty dirs exist with .gitkeep
    for empty in ("instances", "intents", "actionTypes", "intentTypes"):
        assert (tmp_path / "ontology" / empty / ".gitkeep").exists()


def test_init_refuses_to_overwrite_existing(tmp_path: Path):
    (tmp_path / "ontology" / "objectTypes").mkdir(parents=True)
    (tmp_path / "ontology" / "objectTypes" / "Repo.yaml").write_text("kind: ObjectType\n")
    with pytest.raises(FileExistsError, match="Repo.yaml"):
        init_ontology(tmp_path, profile="workspace", manifest_template=MANIFEST_TEMPLATE)


def test_init_single_repo_profile_skips_workspace_only_types(tmp_path: Path):
    report = init_ontology(
        tmp_path, profile="single-repo", manifest_template=MANIFEST_TEMPLATE
    )
    # single-repo profile excludes Protocol / RulesPack / Release (workspace-only)
    assert not (tmp_path / "ontology" / "objectTypes" / "Protocol.yaml").exists()
    assert not (tmp_path / "ontology" / "objectTypes" / "RulesPack.yaml").exists()
    assert not (tmp_path / "ontology" / "objectTypes" / "Release.yaml").exists()
    assert (tmp_path / "ontology" / "objectTypes" / "Module.yaml").exists()
    # Cross-repo link types should also be skipped
    assert not (tmp_path / "ontology" / "linkTypes" / "vendors.yaml").exists()
    assert "objectTypes/Protocol.yaml" in report.skipped_due_to_profile or any(
        s.endswith("Protocol.yaml") for s in report.skipped_due_to_profile
    )


def test_init_rejects_unknown_profile(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown profile"):
        init_ontology(tmp_path, profile="bogus", manifest_template=MANIFEST_TEMPLATE)


def test_init_rejects_missing_template(tmp_path: Path):
    fake = tmp_path / "nope"
    with pytest.raises(FileNotFoundError, match="Template not found"):
        init_ontology(tmp_path, profile="workspace", manifest_template=fake)
