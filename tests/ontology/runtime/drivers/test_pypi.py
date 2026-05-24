from __future__ import annotations

from agent_readiness.ontology.runtime.drivers.pypi import PyPIDriver


def test_pypi_driver_dry_run():
    driver = PyPIDriver()
    result = driver.execute("twine upload dist/*", {"sdist": "dist/foo.whl"}, dry_run=True)
    assert result.success is True
    assert result.command_run == "twine upload dist/*"
    assert result.stdout == "(dry-run)"
    assert result.duration_ms == 0
