"""Core data models for checks and findings."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class Category(str, Enum):
    ONBOARDING = "onboarding"          # A: navigation, README, AGENTS.md
    REPRODUCIBILITY = "reproducibility"  # B: build / run / test
    CONTEXT = "context"                 # C: context-window economics
    FEEDBACK = "feedback"               # D: types, lint, test feedback loop
    LOCALITY = "locality"               # E: complexity, churn, coupling
    HYGIENE = "hygiene"                 # F: secrets, gitignore, license


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class Finding(BaseModel):
    """A single observation from a check.

    Findings are additive evidence; the scorer aggregates them per category.
    """
    check_id: str
    category: Category
    severity: Severity = Severity.INFO
    score_delta: float = 0.0  # how much this finding moves the category score
    message: str
    file: Path | None = None
    line: int | None = None
    fix_hint: str | None = None


class CheckResult(BaseModel):
    """The output of running one check."""
    check_id: str
    category: Category
    score: float = Field(ge=0.0, le=100.0)  # check's contribution, 0–100
    weight: float = 1.0                      # weight within its category
    findings: list[Finding] = Field(default_factory=list)


class CategoryScore(BaseModel):
    category: Category
    score: float = Field(ge=0.0, le=100.0)
    check_results: list[CheckResult] = Field(default_factory=list)


class Report(BaseModel):
    """Top-level report returned by a scan."""
    repo_path: Path
    overall_score: float = Field(ge=0.0, le=100.0)
    category_scores: list[CategoryScore] = Field(default_factory=list)
