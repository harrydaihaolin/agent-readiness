"""Tests for ontology drift propose-pr."""
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from agent_readiness.ontology.drift.detect import detect_drift
from agent_readiness.ontology.drift.propose_pr import PRProposalResult, propose_pr_for_drift


def test_dry_run_emits_yaml_diff_without_writing(tmp_path: Path, fixture_drift_workspace):
    report = detect_drift(fixture_drift_workspace)
    manifest = tmp_path / "fake-manifest"
    manifest.mkdir()
    result = propose_pr_for_drift(
        report=report,
        manifest_repo=manifest,
        dry_run=True,
    )
    assert isinstance(result, PRProposalResult)
    assert result.pr_url is None
    assert result.yaml_diff


def test_apply_mode_writes_files_to_branch(fixture_drift_workspace, fake_manifest_git_repo):
    report = detect_drift(fixture_drift_workspace)
    result = propose_pr_for_drift(
        report=report,
        manifest_repo=fake_manifest_git_repo,
        dry_run=False,
        skip_gh=True,
    )
    branch = subprocess.check_output(
        ["git", "-C", str(fake_manifest_git_repo), "branch", "--list", "drift/*"],
        text=True,
    )
    assert branch.strip()
    assert result.branch is not None


def test_proposed_atoms_carry_proposed_state(fixture_drift_workspace, fake_manifest_git_repo):
    report = detect_drift(fixture_drift_workspace)
    result = propose_pr_for_drift(
        report=report,
        manifest_repo=fake_manifest_git_repo,
        dry_run=False,
        skip_gh=True,
    )
    assert result.branch is not None
    subprocess.check_call(
        ["git", "-C", str(fake_manifest_git_repo), "checkout", result.branch],
    )
    new_files = list((fake_manifest_git_repo / "ontology" / "instances" / "Repo").glob("*.yaml"))
    raw_by_file = {f: yaml.safe_load(f.read_text()) for f in new_files}
    proposed = [data for data in raw_by_file.values() if data.get("lifecycle", {}).get("state") == "proposed"]
    assert proposed, "expected at least one proposed instance on drift branch"
    for data in proposed:
        assert data["lifecycle"]["proposed_by"] == "agent-readiness-bot"


def test_apply_mode_works_without_preconfigured_git_identity(
    fixture_drift_workspace, tmp_path: Path
):
    """Regression: in CI, the manifest checkout has no user.email/user.name set.
    propose_pr_for_drift must supply identity inline via `git -c user.x=...`
    or the commit fails with exit 128."""
    report = detect_drift(fixture_drift_workspace)

    manifest = tmp_path / "fresh-manifest"
    manifest.mkdir()
    (manifest / "ontology" / "instances" / "Repo").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=manifest, check=True)
    subprocess.run(
        ["git", "-C", str(manifest), "config", "user.email", "init@init"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(manifest), "config", "user.name", "init"],
        check=True,
    )
    subprocess.run(["git", "-C", str(manifest), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(manifest), "commit", "--allow-empty", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(manifest), "config", "--unset", "user.email"], check=True)
    subprocess.run(["git", "-C", str(manifest), "config", "--unset", "user.name"], check=True)

    result = propose_pr_for_drift(
        report=report,
        manifest_repo=manifest,
        dry_run=False,
        skip_gh=True,
    )
    assert result.branch is not None
    log_author = subprocess.check_output(
        ["git", "-C", str(manifest), "log", "-1", "--format=%an <%ae>"],
        text=True,
    ).strip()
    assert "agent-readiness-bot" in log_author
