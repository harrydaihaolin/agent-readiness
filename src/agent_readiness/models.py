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
    COORDINATION = "coordination"


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

    The ``action`` and ``verify`` fields surface the deterministic
    action contract introduced in protocol v0.2.0 / rules_version 2.
    They are dicts (not strongly-typed dataclasses) so the engine can
    pass through any of the six action kinds without recompilation —
    consumers already know how to dispatch on ``action.kind``. Both
    fields are None for legacy v1 rules.
    """
    check_id: str
    pillar: Pillar
    message: str
    severity: Severity = Severity.INFO
    file: Path | None = None
    line: int | None = None
    fix_hint: str | None = None
    action: dict[str, Any] | None = None
    verify: dict[str, Any] | None = None
    fix_prompt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["pillar"] = self.pillar.value
        d["severity"] = self.severity.value
        d["file"] = _path_to_str(self.file)
        # Strip the optional v2 fields when null so v1-only consumers
        # don't see schema-noise; they reappear automatically once a
        # rule populates them.
        if d.get("action") is None:
            d.pop("action", None)
        if d.get("verify") is None:
            d.pop("verify", None)
        if d.get("fix_prompt") is None:
            d.pop("fix_prompt", None)
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
    score_impact: float | None = None   # estimated overall-score gain from fixing (set by scorer)
    explanation: str | None = None      # check rationale text (set by CLI from CheckSpec)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "check_id": self.check_id,
            "pillar": self.pillar.value,
            "score": self.score,
            "weight": self.weight,
            "not_measured": self.not_measured,
            "findings": [f.to_dict() for f in self.findings],
        }
        if self.score_impact is not None:
            d["score_impact"] = self.score_impact
        if self.explanation is not None:
            d["explanation"] = self.explanation
        return d


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

    The ``top_action`` field is the EXP-4 per-repo action pin: a single
    deterministic "Start here" for each repo, computed from the priority
    sort `severity=error first > pillar [flow > feedback > safety >
    cognitive_load] > weight desc`. None when the repo has zero
    findings. See ``scorer.compute_top_action``.
    """
    repo_path: Path
    overall_score: float                                    # 0..100, after safety cap
    pillar_scores: list[PillarScore] = field(default_factory=list)
    safety_cap_applied: float | None = None                 # populated when secrets etc. capped the score
    schema: int = 1                                         # JSON schema version, bump on breaking change
    delta: float | None = None                              # overall score delta vs baseline (--baseline)
    languages: list[str] = field(default_factory=list)     # detected programming languages
    monorepo_tools: list[str] = field(default_factory=list) # detected monorepo tooling
    top_action: dict[str, Any] | None = None               # EXP-4 per-repo pinned action

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema": self.schema,
            "repo_path": str(self.repo_path),
            "overall_score": self.overall_score,
            "safety_cap_applied": self.safety_cap_applied,
            "pillars": [p.to_dict() for p in self.pillar_scores],
        }
        if self.languages or self.monorepo_tools:
            d["context"] = {
                "languages": self.languages,
                "monorepo_tools": self.monorepo_tools,
                "is_monorepo": len(self.monorepo_tools) > 0,
            }
        if self.delta is not None:
            d["delta"] = self.delta
        if self.top_action is not None:
            d["top_action"] = self.top_action
        return d


# --- Workspace enumeration ---------------------------------------------

@dataclass
class ChildEnumeration:
    """Static metadata about one entry in an enumeration (root or child)."""
    path: Path
    has_git: bool
    has_readme: bool
    has_agents_md: bool
    top_files: list[str] = field(default_factory=list)
    top_dirs: list[str] = field(default_factory=list)
    language_hint: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "has_git": self.has_git,
            "has_readme": self.has_readme,
            "has_agents_md": self.has_agents_md,
            "top_files": self.top_files,
            "top_dirs": self.top_dirs,
            "language_hint": self.language_hint,
        }


@dataclass
class EnumerationReport:
    """Output of enumerate_workspace(). No scoring, no rule evaluation."""
    root: ChildEnumeration
    children: list[ChildEnumeration]
    manifest_signals: dict[str, bool]
    stats: dict[str, Any]
    schema: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "enumeration",
            "schema": self.schema,
            "root": self.root.to_dict(),
            "children": [c.to_dict() for c in self.children],
            "manifest_signals": self.manifest_signals,
            "stats": self.stats,
        }


# --- Workspace readiness -----------------------------------------------

@dataclass
class ChildReadiness:
    """One child's report inside the workspace envelope.

    ``top_action`` carries the child's own ``compute_top_action`` pin so
    the workspace orchestrator can promote it when there are no
    Coordination findings — without re-scanning the child.
    """
    path: Path
    overall_score: float
    pillar_scores: dict[str, float]
    safety_cap_applied: float | None = None
    top_action: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "path": str(self.path),
            "overall_score": self.overall_score,
            "pillar_scores": self.pillar_scores,
        }
        if self.safety_cap_applied is not None:
            d["safety_cap_applied"] = self.safety_cap_applied
        if self.top_action is not None:
            d["top_action"] = self.top_action
        return d


@dataclass
class WorkspaceReadinessReport:
    """Top-level envelope returned by check_workspace_readiness.

    The Coordination pillar is the only one with workspace-only checks;
    the other four are aggregated from per-child scans. ``safety_caps_applied``
    surfaces any per-child Safety caps so the workspace narration can
    explain why a particular child's safety pillar isn't 100.
    """
    repo_path: Path
    overall_score: float
    pillar_scores: dict[str, float]
    children: list[ChildReadiness]
    coordination_findings: list[Finding]
    top_action: dict[str, Any] | None
    stats: dict[str, Any]
    safety_caps_applied: list[dict[str, Any]]
    schema: int = 1

    def to_dict(self) -> dict[str, Any]:
        pillars: list[dict[str, Any]] = []
        for pillar_name, score in self.pillar_scores.items():
            entry: dict[str, Any] = {
                "pillar": pillar_name,
                "score": score,
                "source": "workspace" if pillar_name == "coordination" else "aggregated",
            }
            if pillar_name == "safety" and self.safety_caps_applied:
                entry["safety_caps_applied"] = self.safety_caps_applied
            if pillar_name == "coordination":
                entry["findings"] = [f.to_dict() for f in self.coordination_findings]
            pillars.append(entry)

        d: dict[str, Any] = {
            "kind": "workspace_readiness",
            "schema": self.schema,
            "repo_path": str(self.repo_path),
            "overall_score": self.overall_score,
            "pillars": pillars,
            "children": [c.to_dict() for c in self.children],
            "stats": self.stats,
        }
        if self.top_action is not None:
            d["top_action"] = self.top_action
        return d
