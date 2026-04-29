"""Private matcher: ``gh_cli_query``.

Shells out to the ``gh`` CLI for GitHub-API-backed checks (currently
just branch rulesets). Silently returns no findings when:
- ``gh`` isn't installed
- the repo isn't a GitHub remote
- ``gh auth status`` fails
…and ``neutral_when_no_gh_cli: true`` is set (the default). In all
those cases the evaluator treats no-findings as a clean score, which
is the right "we cannot measure this from here" outcome.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import register_private_matcher


def _get_remote_owner_repo(ctx: RepoContext) -> tuple[str, str] | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ctx.root, capture_output=True, text=True, check=False, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    m = re.search(r"github\.com[/:]([^/]+)/([^/\s]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)
    return None


def match_gh_cli_query(
    ctx: RepoContext, cfg: dict[str, Any]
) -> list[tuple[str | None, int | None, str]]:
    api_path_template = str(cfg.get("api_path", ""))
    if not api_path_template:
        return []
    fire_when = str(cfg.get("fire_when", "empty"))

    if shutil.which("gh") is None:
        return []
    if not ctx.is_git_repo:
        return []
    owner_repo = _get_remote_owner_repo(ctx)
    if owner_repo is None:
        return []
    owner, repo = owner_repo

    try:
        auth = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if auth.returncode != 0:
        return []

    api_path = api_path_template.format(owner=owner, repo=repo)
    try:
        result = subprocess.run(
            ["gh", "api", api_path],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []

    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return []

    is_empty = (
        payload is None
        or (isinstance(payload, list) and len(payload) == 0)
        or (isinstance(payload, dict) and not payload)
    )

    if fire_when == "empty" and is_empty:
        return [(None, None, f"`gh api {api_path}` returned an empty result for {owner}/{repo}.")]
    if fire_when == "non_empty" and not is_empty:
        return [(None, None, f"`gh api {api_path}` returned a non-empty result for {owner}/{repo}.")]
    return []


register_private_matcher("gh_cli_query", match_gh_cli_query)
