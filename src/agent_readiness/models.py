"""Core data models for checks and findings."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class Pillar(str, Enum):
    """The DevEx-for-agents pillars from RUBRIC.md.

    Every check belongs to exactly one pillar (Safety acts as a cap, not a
    pillar weight, but is modeled the same way for uniformity).
    """
    COGNITIVE_LOAD = "cognitive_load"   # what the agent must absorb
    FEEDBACK = "feedback"                # signal speed and clarity post-change
    FLOW = "flow"                        # friction outside the task itself
    SAFETY = "safety"                    # cap on overall score, not weighted in


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class Finding(BaseModel):
    """A single observation from a check.

    Findings are additive evidence; the scorer aggregates them per pillar.
    """
    check_id: str
    pillar: Pillar
    severity: Severity = Severity.INFO
    score_delta: float = 0.0  # how much this finding moves the pillar score
    message: str
    file: Path | None = None
    line: int | None = None
    fix_hint: str | None = None


class CheckResult(BaseModel):
    """The output of running one check."""
    check_id: str
    pillar: Pillar
    score: float = Field(ge=0.0, le=100.0)  # check's contribution, 0–100
    weight: float = 1.0                      # weight within its pillar
    findings: list[Finding] = Field(default_factory=list)


class PillarScore(BaseModel):
    pillar: Pillar
    score: float = Field(ge=0.0, le=100.0)
    check_results: list[CheckResult] = Field(default_factory=list)


class Report(BaseModel):
    """Top-level report returned by a scan."""
    repo_path: Path
    overall_score: float = Field(ge=0.0, le=100.0)
    pillar_scores: list[PillarScore] = Field(default_factory=list)
