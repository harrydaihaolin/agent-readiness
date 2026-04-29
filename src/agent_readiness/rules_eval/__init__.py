"""Reference (OSS) evaluator for declarative YAML rules.

This subpackage is the canonical interpretation of rule definitions
shipped in ``agent-readiness-rules``. The closed insights engine
implements its own evaluator with additional match types; the OSS
implementation here is what every Bronze user runs and what the
``agent-readiness-rules`` CI uses to validate new rules.

Public API:

    from agent_readiness.rules_eval import (
        load_rules_from_dir,
        evaluate_rules,
        OssMatchTypeRegistry,
    )

The five OSS match types are:

- ``file_size``           — line/byte thresholds with glob exclusions
- ``path_glob``           — required/forbidden file globs
- ``manifest_field``      — fields in pyproject.toml / package.json
- ``regex_in_files``      — regex search in matched files
- ``command_in_makefile`` — Makefile target presence

Anything else (``ast_query``, ``churn_signal``, etc.) belongs in the
closed engine; the loader here drops unknown match types with a
``not_measured`` finding rather than crashing.
"""

from __future__ import annotations

from .evaluator import evaluate_rules
from .loader import LoadedRule, RuleLoadError, load_rules_from_dir
from .matchers import OssMatchTypeRegistry

__all__ = [
    "LoadedRule",
    "RuleLoadError",
    "load_rules_from_dir",
    "evaluate_rules",
    "OssMatchTypeRegistry",
]
