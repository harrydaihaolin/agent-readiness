"""ETA estimator — median per-child duration from last N completed scans."""
from __future__ import annotations

import enum
import statistics
from dataclasses import dataclass


HISTORY_WINDOW = 3
FALLBACK_SECONDS_PER_CHILD = 30


class EtaConfidence(enum.Enum):
    HIGH = "high"
    LOW = "low"


@dataclass
class EtaEstimate:
    minutes: int
    confidence: EtaConfidence


def estimate_eta(*, meta: dict, remaining_children: int) -> EtaEstimate:
    """Return an ETA in whole minutes, with confidence flag."""
    completed = [
        s for s in meta.get("scans", [])
        if s.get("status") == "completed"
        and s.get("per_child_duration_ms_median") is not None
    ][-HISTORY_WINDOW:]
    if not completed:
        secs = remaining_children * FALLBACK_SECONDS_PER_CHILD
        return EtaEstimate(
            minutes=max(1, round(secs / 60)),
            confidence=EtaConfidence.LOW,
        )
    medians = [s["per_child_duration_ms_median"] for s in completed]
    ms = statistics.median(medians)
    secs = (remaining_children * ms) / 1000.0
    return EtaEstimate(
        minutes=max(1, round(secs / 60)),
        confidence=EtaConfidence.HIGH,
    )
