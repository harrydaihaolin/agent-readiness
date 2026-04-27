"""Check: naming.search_precision

Vague file names like utils.py, helpers.py, manager.py reduce an agent's
ability to predict what's in a file from its name. The agent has to read
every "utils" file to determine whether the function it needs is there.
Precise, domain-specific names let the agent navigate the codebase
without reading every file.
"""

from __future__ import annotations

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


# File stems considered ambiguous — domain-agnostic dumping grounds
_AMBIGUOUS_STEMS = frozenset({
    "utils", "helpers", "helper", "manager", "managers",
    "common", "shared", "misc", "base",
    "constants", "config",
    "types", "interfaces",
})


@register(
    check_id="naming.search_precision",
    pillar=Pillar.COGNITIVE_LOAD,
    title="File names are specific (no vague utils/helpers)",
    explanation="""
    Files named utils.py, helpers.py, manager.py, etc. are cognitive
    black holes: an agent searching for a function doesn't know whether
    to look in utils.py or shared.py or helpers.py without reading all of
    them. Domain-specific names (auth.py, payment_gateway.py, etc.) let the
    agent predict file contents from the name alone, cutting search time.
    """,
    weight=0.6,
)
def check_naming_search_precision(ctx: RepoContext) -> CheckResult:
    ambiguous: list[str] = []
    for f in ctx._files:
        stem = f.stem.lower()
        if stem not in _AMBIGUOUS_STEMS:
            continue
        # Only flag shallow files (depth ≤ 2). Files deep in a package structure
        # (e.g. src/myapp/config.py) are less of a navigation problem than
        # a top-level standalone utils.py or helpers.py.
        if len(f.parts) > 2:
            continue
        ambiguous.append(str(f))

    n = len(ambiguous)
    if n == 0:
        score = 100.0
    elif n <= 2:
        score = 80.0
    elif n <= 5:
        score = 60.0
    elif n <= 10:
        score = 40.0
    else:
        score = 0.0

    findings: list[Finding] = []
    if n > 2:
        for path_str in ambiguous[:5]:
            findings.append(Finding(
                check_id="naming.search_precision",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.WARN,
                file=path_str,
                message=f"Ambiguously named file: {path_str}",
                fix_hint="Rename to reflect the domain (e.g. auth_utils.py, payment_helpers.py).",
            ))

    return CheckResult(
        check_id="naming.search_precision",
        pillar=Pillar.COGNITIVE_LOAD,
        score=score,
        weight=0.6,
        findings=findings,
    )
