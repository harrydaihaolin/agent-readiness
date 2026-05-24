from __future__ import annotations

from agent_readiness.ontology.runtime.drivers.git_tag import GitTagDriver


def test_git_tag_driver_dry_run():
    driver = GitTagDriver()
    result = driver.execute(
        "git tag v1.0.0 && git push origin v1.0.0",
        {"tag": "v1.0.0", "remote": "origin"},
        dry_run=True,
    )
    assert result.success is True
    assert "git tag v1.0.0" in result.command_run
    assert result.stdout == "(dry-run)"
