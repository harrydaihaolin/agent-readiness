from __future__ import annotations

from typing import Any

from agent_readiness.ontology.runtime.drivers.base import (
    Driver,
    DriverAuthError,
    DriverResult,
    DriverUnavailableError,
)
from agent_readiness.ontology.runtime.drivers.git_tag import GitTagDriver
from agent_readiness.ontology.runtime.drivers.github_pr import GitHubPRDriver
from agent_readiness.ontology.runtime.drivers.github_release import GitHubReleaseDriver
from agent_readiness.ontology.runtime.drivers.npm import NpmDriver
from agent_readiness.ontology.runtime.drivers.pypi import PyPIDriver

_DRIVER_SINGLETONS: dict[str, Driver] = {
    "pypi": PyPIDriver(),
    "npm": NpmDriver(),
    "git_tag": GitTagDriver(),
    "github_release_create": GitHubReleaseDriver(),
    "github_release": GitHubReleaseDriver(),
    "github_pr": GitHubPRDriver(),
    "github_pr_create": GitHubPRDriver(),
    "registry_write": PyPIDriver(),  # default; refined via side_effect registry
}


class DriverNotFoundError(LookupError):
    """Raised when no driver is registered for a side-effect kind."""


def get_driver(kind: str, side_effect: dict[str, Any] | None = None) -> Driver:
    """Return the driver for ``kind``, optionally disambiguated by side_effect metadata."""
    if kind == "registry_write" and side_effect is not None:
        registry = side_effect.get("registry")
        if registry == "npm":
            return NpmDriver()
        if registry == "pypi":
            return PyPIDriver()
    driver = _DRIVER_SINGLETONS.get(kind)
    if driver is None:
        raise DriverNotFoundError(f"No driver registered for side-effect kind: {kind}")
    return driver


__all__ = [
    "Driver",
    "DriverAuthError",
    "DriverNotFoundError",
    "DriverResult",
    "DriverUnavailableError",
    "GitHubPRDriver",
    "GitHubReleaseDriver",
    "GitTagDriver",
    "NpmDriver",
    "PyPIDriver",
    "get_driver",
]
