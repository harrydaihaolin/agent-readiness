"""Core data models for checks and findings.

Stdlib dataclasses only — no pydantic. Internal-only types, no external
input to validate, so the runtime checks pydantic would buy us aren't
worth the dep. Everything serializable to JSON via `to_dict()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class Pillar(str, Enum):
    """The DevEx-for-agents pillars from RUBRIC.md.

    Every check belongs to exactly one pillar (Safety acts as a cap, not a
    pillar weight, but is modeled the same way for uniformity).
    """
    COGNITIVE_LOAD = "cognitive_load"
    FEEDBACK = "feedback"
    FLOW = "flow"
    SAFETY = "safety"


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


def _path_to_str(p: Path | None) -> str | None:
    return str(p) if p is not None else None


@dataclass
class Finding:
    """A single observation from a check.

    Findings are evidence; the scorer aggregates them per pillar.
    """
    check_id: str
    pillar: Pillar
    message: str
    severity: Severity = Severity.INFO
    file: Path | None = None
    line: int | None = None
    fix_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["pillar"] = self.pillar.value
        d["severity"] = self.severity.value
        d["file"] = _path_to_str(self.file)
        return d


@dataclass
class CheckResult:
    """The output of running one check."""
    check_id: str
    pillar: Pillar
    score: float                # 0..100; check's contribution to its pillar
    weight: float = 1.0         # weight of this check within its pillar
    not_measured: bool = False  # True when this check was skipped (e.g. needs --run)
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "pillar": self.pillar.value,
            "score": self.score,
            "weight": self.weight,
            "not_measured": self.not_measured,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class PillarScore:
    pillar: Pillar
    score: float                       # 0..100; weighted average of check scores
    check_results: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pillar": self.pillar.value,
            "score": self.score,
            "checks": [c.to_dict() for c in self.check_results],
        }


@dataclass
class Report:
    """Top-level report returned by a scan. JSON-serialised under --json.

    Schema versioning:
      schema=1 was established in v0.1 and is the stable contract.
      schema=2 will be bumped on the next intentional breaking change.
      Consumers should check `schema` before parsing.
    """
    repo_path: Path
    overall_score: float                                    # 0..100, after safety cap
    pillar_scores: list[PillarScore] = field(default_factory=list)
    safety_cap_applied: float | None = None                 # populated when secrets etc. capped the score
    schema: int = 1                                         # JSON schema version, bump on breaking change
    delta: float | None = None                              # overall score delta vs baseline (--baseline)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema": self.schema,
            "repo_path": str(self.repo_path),
            "overall_score": self.overall_score,
            "safety_cap_applied": self.safety_cap_applied,
            "pillars": [p.to_dict() for p in self.pillar_scores],
        }
        if self.delta is not None:
            d["delta"] = self.delta
        return d
