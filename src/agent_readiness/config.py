"""Load and parse .agent-readiness.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

from agent_readiness.models import Pillar
from agent_readiness.scorer import DEFAULT_WEIGHTS


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
