"""OSS-shipped private matchers for the declarative rules pack.

This package is the bridge between YAML rules in `agent-readiness-rules`
that reference imperative analyses (`type: git_log_query`,
`type: ast_complexity`, …) and the Python implementations of those
analyses. Importing this package registers every matcher with the OSS
`rules_eval` evaluator via `register_private_matcher`.

Each module here:
- Imports `register_private_matcher` from the parent `rules_eval` package
- Defines a `match_<type>(ctx, cfg) -> list[(file, line, msg)]` function
- Calls `register_private_matcher("<type>", match_<type>)` at import time

Adding a new private matcher: drop a module here, import it below. The
side-effect import is intentional — the OSS scan command and the
`rules-eval` subcommand both need every matcher registered before they
load any YAML rule that references its `type`.

These are the *OSS* private matchers. Downstream engines
(`agent-readiness-pro`, the closed insights engine) layer their own on
top via the same `register_private_matcher` API; the OSS set is the
floor every install gets.
"""

from __future__ import annotations

from . import (  # noqa: F401  -- import for side effect (registration)
    ast_complexity,
    cross_file_consistency,
    gh_cli_query,
    git_log_query,
    gitignore_coverage,
    manifest_introspection,
    naming_search,
    prompt_scan,
    regex_secret_scan,
    setup_command_count,
    tree_aggregate,
)

__all__: list[str] = []
