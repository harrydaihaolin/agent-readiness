"""Check: setup.command_count

The fewer distinct shell commands an agent needs to run to set up a
project, the better. Each additional step is a point of failure, a
potential for env-specific breakage, and cognitive overhead. Ideally
setup is one command (make install, npm install, etc.).
"""

from __future__ import annotations

import re

from agent_readiness.checks import register
from agent_readiness.context import RepoContext
from agent_readiness.models import CheckResult, Finding, Pillar, Severity


_SETUP_HEADINGS = re.compile(
    r"(?im)^\s*#{1,6}\s*(install(ation)?|setup|getting started|quick ?start)\b.*$"
)
_NEXT_HEADING = re.compile(r"(?m)^\s*#{1,6}\s+\S")

# Lines starting with $
_SHELL_PROMPT = re.compile(r"^\s*\$\s+\S")
# Fenced bash/sh blocks
_FENCE_OPEN = re.compile(r"^```\s*(bash|sh|shell|zsh|console)\s*$", re.I)
_FENCE_CLOSE = re.compile(r"^```\s*$")
# Command lines inside a fenced block (non-empty, non-comment)
_CMD_LINE = re.compile(r"^\s*[^#\s]")


def _extract_setup_section(text: str) -> str:
    m = _SETUP_HEADINGS.search(text)
    if m is None:
        return ""
    start = m.end()
    next_h = _NEXT_HEADING.search(text, pos=start)
    end = next_h.start() if next_h else len(text)
    return text[start:end]


def _count_commands(text: str) -> int:
    commands: set[str] = set()
    lines = text.splitlines()
    in_fence = False
    for line in lines:
        if not in_fence:
            if _FENCE_OPEN.match(line):
                in_fence = True
                continue
            m = _SHELL_PROMPT.match(line)
            if m:
                cmd = line.strip().lstrip("$").strip()
                commands.add(cmd)
        else:
            if _FENCE_CLOSE.match(line):
                in_fence = False
                continue
            if _CMD_LINE.match(line):
                cmd = line.strip()
                commands.add(cmd)
    return len(commands)


@register(
    check_id="setup.command_count",
    pillar=Pillar.FLOW,
    title="Setup requires few commands",
    explanation="""
    Each additional step in the setup process is another opportunity for
    an agent to encounter an unexpected error, wait for I/O, or need to
    make a decision. Single-command setup (make install, npm install) is
    the ideal: deterministic, fast, and copy-pasteable.
    """,
    weight=0.7,
)
def check_setup_command_count(ctx: RepoContext) -> CheckResult:
    # Find README
    readme = ctx.has_file("README.md", "README.rst", "README.txt", "README")
    if readme is None:
        return CheckResult(
            check_id="setup.command_count",
            pillar=Pillar.FLOW,
            score=100.0,
            weight=0.7,
        )

    text = ctx.read_text(readme) or ""
    section = _extract_setup_section(text)

    if not section.strip():
        return CheckResult(
            check_id="setup.command_count",
            pillar=Pillar.FLOW,
            score=100.0,
            weight=0.7,
        )

    n = _count_commands(section)

    if n <= 2:
        score = 100.0
    elif n == 3:
        score = 80.0
    elif n <= 5:
        score = 60.0
    else:
        score = 0.0

    findings: list[Finding] = []
    if n > 5:
        findings.append(Finding(
            check_id="setup.command_count",
            pillar=Pillar.FLOW,
            severity=Severity.WARN,
            message=f"Setup section has {n} distinct commands — consider wrapping in make install or a setup script.",
            fix_hint="Wrap multi-step setup into a single `make install` or `./scripts/setup` command.",
        ))

    return CheckResult(
        check_id="setup.command_count",
        pillar=Pillar.FLOW,
        score=score,
        weight=0.7,
        findings=findings,
    )
