from __future__ import annotations

from agent_readiness.ontology.runtime.drivers.github_release import GitHubReleaseDriver


def test_github_release_driver_dry_run():
    driver = GitHubReleaseDriver()
    result = driver.execute(
        "gh release create v1.0.0",
        {"tag": "v1.0.0"},
        dry_run=True,
    )
    assert result.success is True
    assert result.command_run == "gh release create v1.0.0"
    assert result.stdout == "(dry-run)"
