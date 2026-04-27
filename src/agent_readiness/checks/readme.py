"""Check: readme.has_run_instructions

A README that explains *what this is* and *how to run it* is the cheapest,
highest-leverage piece of agent context. The agent's first action on a
new repo is to read the README. If it doesn't tell the agent how to
install / run / test, the agent has to guess — which means scanning the
manifest, looking for scripts, asking the user. Every minute spent
guessing is a minute not spent on the task.

Scoring (0..100):
- README missing entirely:                                     0
- README present but has no run / install / test signal:      40
- README has at least one of (install / run / test) signals:  80
- README has at least two of those signals + fenced code:    100
"""

from __future__ import annotations

import re

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


_README_NAMES = ("README.md", "README.rst", "README.txt", "README")
_FENCE_RE = re.compile(r"```|~~~")
_INSTALL_RE = re.compile(r"\b(install|installation|setup|getting started)\b", re.I)
_RUN_RE = re.compile(r"\b(run|usage|quick ?start|how to use)\b", re.I)
_TEST_RE = re.compile(r"\btest(s|ing)?\b", re.I)


@register(
    check_id="readme.has_run_instructions",
    pillar=Pillar.COGNITIVE_LOAD,
    title="README explains how to install, run, and test",
    explanation="""
    Agents start by reading README.md. A README that doesn't say how to
    install dependencies, run the project, and execute tests forces the
    agent to guess from manifest files and shell history — slow at best,
    wrong at worst. We look for explicit install / run / test signals
    plus at least one fenced code block (the part the agent can copy
    verbatim).
    """,
)
def check(ctx: RepoContext) -> CheckResult:
    findings: list[Finding] = []
    readme = ctx.has_file(*_README_NAMES)

    if readme is None:
        findings.append(Finding(
            check_id="readme.has_run_instructions",
            pillar=Pillar.COGNITIVE_LOAD,
            severity=Severity.WARN,
            message="No README found at repo root.",
            fix_hint="Add a README.md with install / run / test sections.",
        ))
        return CheckResult("readme.has_run_instructions", Pillar.COGNITIVE_LOAD,
                           score=0.0, findings=findings)

    text = ctx.read_text(readme) or ""
    has_install = bool(_INSTALL_RE.search(text))
    has_run = bool(_RUN_RE.search(text))
    has_test = bool(_TEST_RE.search(text))
    has_fence = bool(_FENCE_RE.search(text))
    signal_count = sum([has_install, has_run, has_test])

    if signal_count == 0:
        score = 40.0
        findings.append(Finding(
            check_id="readme.has_run_instructions",
            pillar=Pillar.COGNITIVE_LOAD,
            severity=Severity.WARN,
            file=readme,
            message="README has no install / run / test sections.",
            fix_hint="Add headings like 'Install', 'Run', or 'Test' with commands.",
        ))
    elif signal_count >= 2 and has_fence:
        score = 100.0
    else:
        score = 80.0
        if not has_fence:
            findings.append(Finding(
                check_id="readme.has_run_instructions",
                pillar=Pillar.COGNITIVE_LOAD,
                severity=Severity.INFO,
                file=readme,
                message="README has run-related sections but no fenced code blocks.",
                fix_hint="Wrap commands in ```bash ... ``` so agents can copy them verbatim.",
            ))

    return CheckResult(
        check_id="readme.has_run_instructions",
        pillar=Pillar.COGNITIVE_LOAD,
        score=score,
        findings=findings,
    )
