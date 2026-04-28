"""Load and parse .agent-readiness.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

from agent_readiness.models import Pillar
from agent_readiness.scorer import DEFAULT_WEIGHTS


# Named weight presets for common use-cases.
# "default" mirrors DEFAULT_WEIGHTS; "strict" emphasises fast feedback loops;
# "lax" is more forgiving for doc-heavy or exploratory repos.
NAMED_PRESETS: dict[str, dict[str, float]] = {
    "default": {
        "feedback": DEFAULT_WEIGHTS[Pillar.FEEDBACK],
        "cognitive_load": DEFAULT_WEIGHTS[Pillar.COGNITIVE_LOAD],
        "flow": DEFAULT_WEIGHTS[Pillar.FLOW],
    },
    "strict": {
        "feedback": 0.50,
        "cognitive_load": 0.25,
        "flow": 0.25,
    },
    "lax": {
        "feedback": 0.30,
        "cognitive_load": 0.40,
        "flow": 0.30,
    },
}


def load_config(repo_root: Path) -> dict:
    """Load .agent-readiness.toml from repo root. Returns {} if missing."""
    path = repo_root / ".agent-readiness.toml"
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def extract_weights(config: dict) -> dict[Pillar, float] | None:
    """Extract pillar weights from config dict. Returns None if no [weights] section."""
    w = config.get("weights", {})
    if not w:
        return None
    result = dict(DEFAULT_WEIGHTS)
    mapping = {
        "feedback": Pillar.FEEDBACK,
        "cognitive_load": Pillar.COGNITIVE_LOAD,
        "flow": Pillar.FLOW,
    }
    for key, pillar in mapping.items():
        if key in w:
            result[pillar] = float(w[key])
    return result


def resolve_weights(value: str | Path | None) -> dict[Pillar, float] | None:
    """Resolve --weights to a pillar-weight dict.

    Accepts:
    - None            → use defaults (returns None, caller applies DEFAULT_WEIGHTS)
    - A named preset  → one of 'default', 'strict', 'lax'
    - A file path     → TOML file with a [weights] section

    Raises FileNotFoundError if *value* is not a known preset and the path
    does not exist (preserving existing behaviour for invalid paths).
    """
    if value is None:
        return None
    name = str(value)
    if name in NAMED_PRESETS:
        preset = NAMED_PRESETS[name]
        return extract_weights({"weights": preset})
    # Fall back to treating it as a file path
    p = Path(value)
    with p.open("rb") as f:
        wf_data = tomllib.load(f)
    return extract_weights(wf_data)


def extract_context_config(config: dict) -> dict:
    """Extract [context] settings from config dict.

    Supported keys (with defaults):
      token_budget_warn = 16000   # tokens at which repo_shape.token_budget WARNs
      token_budget_max  = 80000   # tokens at which score drops to 0
    """
    ctx = config.get("context", {})
    return {
        "token_budget_warn": int(ctx.get("token_budget_warn", 16_000)),
        "token_budget_max": int(ctx.get("token_budget_max", 80_000)),
    }
