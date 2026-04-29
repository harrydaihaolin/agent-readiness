"""Private matcher: ``setup_command_count``.

Counts distinct shell commands in the README's Setup / Installation
section (heading-delimited). Fires when the count exceeds
``max_commands``. No README → no findings (and the readme rule covers
that case separately).
"""

from __future__ import annotations

import re
from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher

_README_NAMES = ("README.md", "README.rst", "README.txt", "README")
_NEXT_HEADING = re.compile(r"(?m)^\s*#{1,6}\s+\S")
_SHELL_PROMPT = re.compile(r"^\s*[\$>]\s+\S")
_FENCE_OPEN = re.compile(
    r"^```\s*(bash|sh|shell|zsh|console|powershell|posh|ps|cmd|batch|python|pip)\s*$",
    re.I,
)
_FENCE_CLOSE = re.compile(r"^```\s*$")
_CMD_LINE = re.compile(r"^\s*[^#\s]")


def _build_setup_heading_regex(headings: tuple[str, ...]) -> re.Pattern[str]:
    if not headings:
        headings = ("install", "installation", "setup", "getting started", "quick ?start")
    pattern = "|".join(re.escape(h) for h in headings)
    return re.compile(rf"(?im)^\s*#{{1,6}}\s*({pattern})\b.*$")


def _extract_setup_section(text: str, headings: tuple[str, ...]) -> str:
    heading_re = _build_setup_heading_regex(headings)
    m = heading_re.search(text)
    if m is None:
        return ""
    start = m.end()
    nh = _NEXT_HEADING.search(text, pos=start)
    end = nh.start() if nh else len(text)
    return text[start:end]


def _count_commands(text: str) -> int:
    commands: set[str] = set()
    in_fence = False
    for line in text.splitlines():
        if not in_fence:
            if _FENCE_OPEN.match(line):
                in_fence = True
                continue
            m = _SHELL_PROMPT.match(line)
            if m:
                commands.add(line.strip().lstrip("$").strip())
        else:
            if _FENCE_CLOSE.match(line):
                in_fence = False
                continue
            if _CMD_LINE.match(line):
                commands.add(line.strip())
    return len(commands)


def match_setup_command_count(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    max_commands = int(cfg.get("max_commands", 5))
    headings = tuple(cfg.get("setup_headings") or ())

    readme = ctx.has_file(*_README_NAMES)
    if readme is None:
        return []
    text = ctx.read_text(readme) or ""
    section = _extract_setup_section(text, headings)
    if not section.strip():
        return []
    n = _count_commands(section)
    if n <= max_commands:
        return []
    return [(
        readme, None,
        f"Setup section has {n} distinct commands — consider wrapping in `make install` "
        "or a setup script.",
    )]


register_private_matcher("setup_command_count", match_setup_command_count)
