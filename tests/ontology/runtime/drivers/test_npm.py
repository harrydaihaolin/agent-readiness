from __future__ import annotations

from agent_readiness.ontology.runtime.drivers.npm import NpmDriver


def test_npm_driver_dry_run():
    driver = NpmDriver()
    result = driver.execute("npm publish", {}, dry_run=True)
    assert result.success is True
    assert result.command_run == "npm publish"
    assert result.stdout == "(dry-run)"
