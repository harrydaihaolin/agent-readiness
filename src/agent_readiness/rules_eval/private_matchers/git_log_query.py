"""Private matcher: ``git_log_query``.

Two YAML modes:
- ``mode: commit_count`` — fires when the repo has fewer than
  ``min_commits`` commits. Used by ``git.has_history``.
- ``mode: churn_hotspots`` — fires per file that has been touched
  ``>= min_commits_touching_file`` times AND has ``> min_file_lines``
  lines. Used by ``git.churn_hotspots``.

Both modes silently produce no findings on shallow clones when
``neutral_on_shallow: true`` (the evaluator scores no-findings as 100,
which is the right "we can't measure this" outcome).
"""

from __future__ import annotations

import subprocess
from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher


def _is_shallow(ctx: RepoContext) -> bool:
    return (ctx.root / ".git" / "shallow").is_file()


def _commit_count_mode(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    if cfg.get("neutral_on_shallow", True) and _is_shallow(ctx):
        return []
    min_commits = int(cfg.get("min_commits", 5))
    fire_when = str(cfg.get("fire_when", "too_few"))
    count = ctx.commit_count
    if fire_when == "too_few" and count < min_commits:
        if count == 0:
            return [(None, None, "Repository has no commits (not a git repo or empty).")]
        return [(None, None, f"Repository has {count} commits — fewer than min_commits={min_commits}.")]
    return []


def _churn_hotspots_mode(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    if cfg.get("neutral_on_shallow", True) and _is_shallow(ctx):
        return []
    min_touches = int(cfg.get("min_commits_touching_file", 10))
    min_lines = int(cfg.get("min_file_lines", 200))
    max_findings = int(cfg.get("max_findings", 5))

    # Same minimum-history gate as the original Python check: below this
    # the churn signal is too noisy to trust.
    if ctx.commit_count < 5:
        return []

    try:
        result = subprocess.run(
            ["git", "log", "--numstat", "--pretty=format:", "--", "."],
            cwd=ctx.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []

    change_count: dict[str, int] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        adds, dels, filename = parts[0], parts[1], parts[2]
        if adds == "-" or dels == "-":  # binary
            continue
        if " => " in filename:  # rename
            continue
        change_count[filename] = change_count.get(filename, 0) + 1

    hotspots: list[tuple[str, int]] = []
    for filename, count in change_count.items():
        if count < min_touches:
            continue
        full = ctx.root / filename
        if not full.is_file():
            continue
        text = ctx.read_text(filename, max_bytes=256_000)
        if text is not None and text.count("\n") > min_lines:
            hotspots.append((filename, count))

    hotspots.sort(key=lambda x: x[1], reverse=True)
    return [
        (filename, None, f"Hotspot: {filename} changed {n} times and is >{min_lines} lines.")
        for filename, n in hotspots[:max_findings]
    ]


def match_git_log_query(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    mode = str(cfg.get("mode", "commit_count"))
    if mode == "commit_count":
        return _commit_count_mode(ctx, cfg)
    if mode == "churn_hotspots":
        return _churn_hotspots_mode(ctx, cfg)
    # Unknown mode — fail closed (no findings) rather than crash.
    return []


register_private_matcher("git_log_query", match_git_log_query)
