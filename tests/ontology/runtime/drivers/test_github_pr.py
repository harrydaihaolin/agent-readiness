from __future__ import annotations

from agent_readiness.ontology.runtime.drivers.github_pr import GitHubPRDriver


def test_github_pr_driver_dry_run():
    driver = GitHubPRDriver()
    result = driver.execute(
        "gh pr create --title 'rename module'",
        {"title": "rename module"},
        dry_run=True,
    )
    assert result.success is True
    assert result.command_run == "gh pr create --title 'rename module'"
    assert result.stdout == "(dry-run)"
