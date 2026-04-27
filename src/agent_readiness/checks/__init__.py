"""Check protocol and registry.

A "check" is a callable that takes a RepoContext and returns a CheckResult.
We use a Protocol rather than an ABC so testing fakes don't need
inheritance, and a decorator-based registry so adding a check is one
@register away.

Every check ships with:
- check_id   (stable identifier, used in JSON output and `explain`)
- pillar     (which pillar it scores into)
- weight     (relative weight within the pillar; default 1.0)
- title      (one-line human description)
- explanation (multi-line; surfaced by `agent-readiness explain <id>`)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Pillar


class CheckFn(Protocol):
    """A check function: pure-ish, deterministic, takes RepoContext."""
    def __call__(self, ctx: RepoContext) -> CheckResult: ...


@dataclass(frozen=True)
class CheckSpec:
    """Metadata + the runnable for a single check."""
    check_id: str
    pillar: Pillar
    title: str
    explanation: str
    fn: CheckFn
    weight: float = 1.0


# Registry is module-level. Order of registration is preserved (Python 3.7+
# dict iteration is insertion-ordered), which makes report output stable.
_REGISTRY: dict[str, CheckSpec] = {}


def register(
    check_id: str,
    pillar: Pillar,
    title: str,
    explanation: str,
    weight: float = 1.0,
) -> Callable[[CheckFn], CheckFn]:
    """Decorator: register a check function under `check_id`.

    Raises if the same check_id is registered twice — that would silently
    drop one of the checks at import time, which is a bug we'd rather
    surface loudly.
    """
    def deco(fn: CheckFn) -> CheckFn:
        if check_id in _REGISTRY:
            raise ValueError(f"duplicate check registration: {check_id!r}")
        _REGISTRY[check_id] = CheckSpec(
            check_id=check_id,
            pillar=pillar,
            title=title,
            explanation=explanation.strip(),
            fn=fn,
            weight=weight,
        )
        return fn
    return deco


def all_checks() -> list[CheckSpec]:
    """Return all registered check specs in registration order."""
    return list(_REGISTRY.values())


def get_check(check_id: str) -> CheckSpec | None:
    return _REGISTRY.get(check_id)


def _ensure_loaded() -> None:
    """Force-import the check modules so their @register decorators fire.

    Called by the CLI before scoring. Adding a new check is: drop a module
    in agent_readiness.checks, import it from here, done.
    """
    # Imported for side effect: each module's @register calls populate
    # _REGISTRY at import time.
    from agent_readiness.checks import (  # noqa: F401
        readme,
        agent_docs,
        test_command,
        headless,
        secrets,
    )
