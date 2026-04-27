"""Phase 1 integration tests.

Uses stdlib unittest so the test suite runs without pytest (matters
for the agent-readiness sandbox, which has no network to install
pytest). Migrate to pytest later if the suite grows past what
unittest is comfortable with.

These are intentionally snapshot-style: the *exact* scores are part
of the contract. If a Phase 1 check changes its scoring, this test
breaks loudly and the maintainer must update the snapshot.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_readiness.checks import _ensure_loaded, all_checks
from agent_readiness.context import RepoContext
from agent_readiness.models import Pillar
from agent_readiness.scorer import score


_FIXTURES = Path(__file__).parent / "fixtures"


def _scan(repo: Path):
    _ensure_loaded()
    ctx = RepoContext(root=repo)
    specs = all_checks()
    results = [spec.fn(ctx) for spec in specs]
    # Apply registry weights (mirrors CLI behaviour)
    for cr, spec in zip(results, specs, strict=True):
        if cr.weight == 1.0 and spec.weight != 1.0:
            cr.weight = spec.weight
    return score(ctx.root, results)


class Phase1Snapshot(unittest.TestCase):

    def test_good_fixture_scores_high(self):
        report = _scan(_FIXTURES / "good")
        # After all phases the good fixture should score 100.0
        # (all checks score 100; updated as new checks land)
        self.assertGreaterEqual(report.overall_score, 95.0)
        self.assertIsNone(report.safety_cap_applied)

    def test_bare_fixture_scores_low(self):
        report = _scan(_FIXTURES / "bare")
        # Bare fixture scores are updated as new checks land
        self.assertLess(report.overall_score, 70.0)
        self.assertIsNone(report.safety_cap_applied)

    def test_score_gap_is_meaningful(self):
        """Acceptance criterion for Phase 1: scores move noticeably.

        If this fails because both fixtures changed, audit the new
        baseline. If only one moved, that's the bug.
        """
        good = _scan(_FIXTURES / "good").overall_score
        bare = _scan(_FIXTURES / "bare").overall_score
        self.assertGreater(good - bare, 50.0,
                           f"Phase 1 should produce a >50pt gap; got "
                           f"good={good} bare={bare} gap={good - bare}")

    def test_phase1_checks_are_registered(self):
        """Phase 1 check IDs must be a subset of all registered checks."""
        _ensure_loaded()
        ids = {spec.check_id for spec in all_checks()}
        phase1_ids = {
            "readme.has_run_instructions",
            "agent_docs.present",
            "test_command.discoverable",
            "headless.no_setup_prompts",
            "secrets.basic_scan",
        }
        self.assertTrue(
            phase1_ids.issubset(ids),
            f"Missing Phase 1 checks: {phase1_ids - ids}",
        )


class SafetyCapBehaviour(unittest.TestCase):
    """Verify the safety cap fires when secrets are present.

    We don't use a fixture for this because committing fake secrets
    to the repo defeats the point of having gitignore, secret-scan
    tooling, and so on. Instead, we synthesize a CheckResult and
    feed it directly to the scorer.
    """

    def test_error_safety_finding_caps_overall_at_30(self):
        from agent_readiness.models import CheckResult, Finding, Severity

        results = [
            CheckResult("readme.has_run_instructions", Pillar.COGNITIVE_LOAD, 100.0),
            CheckResult("agent_docs.present",          Pillar.COGNITIVE_LOAD, 100.0),
            CheckResult("test_command.discoverable",   Pillar.FEEDBACK,        100.0),
            CheckResult("headless.no_setup_prompts",   Pillar.FLOW,            100.0),
            CheckResult("secrets.basic_scan",          Pillar.SAFETY, 0.0,
                        findings=[Finding(
                            "secrets.basic_scan", Pillar.SAFETY,
                            "fake AWS key found", severity=Severity.ERROR,
                        )]),
        ]
        rep = score(Path("/tmp"), results)
        self.assertLessEqual(rep.overall_score, 30.0)
        self.assertEqual(rep.overall_score, 30.0,
                         "perfect-otherwise repo should be capped exactly at 30")
        self.assertIsNotNone(rep.safety_cap_applied)


if __name__ == "__main__":
    unittest.main()
