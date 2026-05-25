"""Emit a PR back to agent-readiness-manifest that resolves a DriftReport.

All atoms emitted in proposed state. Never auto-ratifies.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

import yaml

from agent_readiness_insights_protocol.ontology.drift import DriftKind, DriftReport

_DEFAULT_BOT_NAME = "agent-readiness-bot[bot]"
_DEFAULT_BOT_EMAIL = "agent-readiness-bot[bot]@users.noreply.github.com"


@dataclass
class PRProposalResult:
    pr_url: str | None
    branch: str | None
    yaml_diff: str
    files_created: list[Path]
    files_modified: list[Path]
    files_deleted: list[Path]


def propose_pr_for_drift(
    report: DriftReport,
    manifest_repo: Path,
    dry_run: bool = True,
    skip_gh: bool = False,
) -> PRProposalResult:
    diff_chunks: list[str] = []
    files_created: list[Path] = []
    files_modified: list[Path] = []
    files_deleted: list[Path] = []

    for delta in report.deltas:
        if delta.kind == DriftKind.ADDED and delta.atom_type == "Repo":
            target = manifest_repo / "ontology" / "instances" / "Repo" / f"{delta.atom_id}.yaml"
            payload = _render_proposed_repo_instance(delta.atom_id)
            diff_chunks.append(f"+ {target.relative_to(manifest_repo)}:\n{payload}\n")
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(payload)
                files_created.append(target)
        elif delta.kind == DriftKind.REMOVED and delta.atom_type == "Repo":
            target = manifest_repo / "ontology" / "instances" / "Repo" / f"{delta.atom_id}.yaml"
            diff_chunks.append(f"- {target.relative_to(manifest_repo)} (deleted)\n")
            if not dry_run:
                target.unlink(missing_ok=True)
                files_deleted.append(target)
        elif delta.kind == DriftKind.RENAMED and delta.atom_type == "Repo":
            old = manifest_repo / "ontology" / "instances" / "Repo" / f"{delta.atom_id}.yaml"
            new = manifest_repo / "ontology" / "instances" / "Repo" / f"{delta.new_id}.yaml"
            diff_chunks.append(f"~ rename {old.name} → {new.name}\n")
            if not dry_run:
                if old.exists():
                    body = yaml.safe_load(old.read_text())
                    body["metadata"]["id"] = delta.new_id
                    body["lifecycle"]["state"] = "proposed"
                    body["lifecycle"]["proposed_by"] = "agent-readiness-bot"
                    body["lifecycle"]["markers"] = ["metadata.id (renamed; needs human ratification)"]
                    body["lifecycle"]["ratified_by"] = None
                    body["lifecycle"]["ratified_at"] = None
                    new.write_text(yaml.safe_dump(body, sort_keys=False))
                    old.unlink()
                    files_created.append(new)
                    files_deleted.append(old)
        elif delta.kind == DriftKind.CHANGED and delta.atom_type == "Repo":
            target = manifest_repo / "ontology" / "instances" / "Repo" / f"{delta.atom_id}.yaml"
            diff_chunks.append(
                f"~ {target.relative_to(manifest_repo)} "
                f"(properties changed: {delta.changed_properties})\n"
            )
            if not dry_run and target.exists():
                body = yaml.safe_load(target.read_text())
                body["lifecycle"]["state"] = "proposed"
                body["lifecycle"]["proposed_by"] = "agent-readiness-bot"
                body["lifecycle"]["markers"] = [f"spec.properties.{p}" for p in delta.changed_properties]
                body["lifecycle"]["ratified_by"] = None
                body["lifecycle"]["ratified_at"] = None
                target.write_text(yaml.safe_dump(body, sort_keys=False))
                files_modified.append(target)

    yaml_diff = "\n".join(diff_chunks)

    branch_name = None
    pr_url = None
    if not dry_run:
        branch_name = f"drift/scan-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        bot_name = os.environ.get("AR_BOT_GIT_NAME", _DEFAULT_BOT_NAME)
        bot_email = os.environ.get("AR_BOT_GIT_EMAIL", _DEFAULT_BOT_EMAIL)
        git_identity_args = [
            "-c", f"user.name={bot_name}",
            "-c", f"user.email={bot_email}",
        ]

        subprocess.run(
            ["git", "-C", str(manifest_repo), "checkout", "-b", branch_name],
            check=True,
        )
        subprocess.run(["git", "-C", str(manifest_repo), "add", "-A"], check=True)
        subprocess.run(
            [
                "git", "-C", str(manifest_repo),
                *git_identity_args,
                "commit", "-m",
                f"chore(drift): auto-PR from ontology scan ({len(report.deltas)} deltas)",
            ],
            check=True,
        )

        if not skip_gh:
            import sys

            push = subprocess.run(
                ["git", "-C", str(manifest_repo), "push", "-u", "origin", branch_name],
                capture_output=True, text=True,
            )
            if push.returncode != 0:
                sys.stderr.write(
                    f"git push failed (rc={push.returncode}):\n"
                    f"  stdout: {push.stdout.strip()}\n"
                    f"  stderr: {push.stderr.strip()}\n"
                )
                return PRProposalResult(
                    pr_url=None,
                    branch=branch_name,
                    yaml_diff=yaml_diff,
                    files_created=files_created,
                    files_modified=files_modified,
                    files_deleted=files_deleted,
                )

            pr_body = _render_pr_body(report)
            result = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--title",
                    f"drift: {len(report.deltas)} ontology deltas (severity={report.severity_level})",
                    "--body", pr_body,
                    "--head", branch_name,
                    "--label", "ontology-drift",
                ],
                cwd=manifest_repo, capture_output=True, text=True,
            )
            if result.returncode == 0:
                pr_url = result.stdout.strip()
            else:
                sys.stderr.write(
                    f"gh pr create failed (rc={result.returncode}):\n"
                    f"  stdout: {result.stdout.strip()}\n"
                    f"  stderr: {result.stderr.strip()}\n"
                )
                issue_result = subprocess.run(
                    [
                        "gh", "issue", "create",
                        "--title",
                        f"drift: {len(report.deltas)} ontology deltas (PR-create denied)",
                        "--body", pr_body,
                        "--label", "ontology-drift",
                    ],
                    cwd=manifest_repo, capture_output=True, text=True,
                )
                if issue_result.returncode == 0:
                    pr_url = issue_result.stdout.strip()
                else:
                    sys.stderr.write(
                        f"gh issue create also failed (rc={issue_result.returncode}):\n"
                        f"  stdout: {issue_result.stdout.strip()}\n"
                        f"  stderr: {issue_result.stderr.strip()}\n"
                    )
                    pr_url = None

    return PRProposalResult(
        pr_url=pr_url,
        branch=branch_name,
        yaml_diff=yaml_diff,
        files_created=files_created,
        files_modified=files_modified,
        files_deleted=files_deleted,
    )


def _render_proposed_repo_instance(atom_id: str) -> str:
    return dedent(f"""\
        apiVersion: agent-readiness.io/v1
        kind: ObjectInstance
        metadata:
          object_type: Repo
          id: {atom_id}
        spec:
          properties:
            name: {atom_id}
            languages: "???"
            primary_manifest: "???"
        lifecycle:
          state: proposed
          proposed_by: agent-readiness-bot
          proposed_at: {datetime.now(timezone.utc).isoformat()}
          confidence: 0.40
          markers:
            - spec.properties.languages
            - spec.properties.primary_manifest
    """)


def _render_pr_body(report: DriftReport) -> str:
    lines = [
        "# Ontology drift detected",
        "",
        f"**Severity:** {report.severity_level} (score {report.severity_score})",
        "",
        "## Deltas",
        "",
    ]
    for d in report.deltas:
        if d.kind == DriftKind.RENAMED:
            lines.append(f"- `{d.kind.value}`: `{d.atom_id}` → `{d.new_id}` ({d.atom_type})")
        elif d.kind == DriftKind.CHANGED:
            lines.append(
                f"- `{d.kind.value}`: `{d.atom_id}` ({d.atom_type}) "
                f"— properties: {d.changed_properties}"
            )
        else:
            lines.append(f"- `{d.kind.value}`: `{d.atom_id}` ({d.atom_type})")
    lines += [
        "",
        "All new / changed instances are `proposed`-state. A human ratifier must resolve "
        "markers and update `ratified_by` before merge consumers can rely on them.",
        "",
        "_Opened by `agent-readiness-bot` from "
        "`agent-readiness ontology drift propose-pr --apply`._",
    ]
    return "\n".join(lines)
