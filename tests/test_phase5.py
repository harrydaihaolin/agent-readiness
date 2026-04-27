"""Phase 5 tests: complexity and churn checks."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_readiness.checks import _ensure_loaded, all_checks
from agent_readiness.context import RepoContext
from agent_readiness.checks.churn import check_churn_hotspots, check_code_complexity


_FIXTURES = Path(__file__).parent / "fixtures"


class ChurnHotspotsCheck(unittest.TestCase):

    def test_check_id_correct(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_churn_hotspots(ctx)
        self.assertEqual(result.check_id, "git.churn_hotspots")

    def test_fixture_not_measured_or_100(self):
        """Fixtures are in the outer git repo but we check that if measured,
        the result is valid (0..100)."""
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_churn_hotspots(ctx)
        # Either not_measured (< 5 commits touching the fixture) or a valid score
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 100.0)

    def test_weight_is_0_6(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_churn_hotspots(ctx)
        self.assertEqual(result.weight, 0.6)


class CodeComplexityCheck(unittest.TestCase):

    def test_check_id_correct(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_code_complexity(ctx)
        self.assertEqual(result.check_id, "code.complexity")

    def test_not_measured_without_lizard_or_good_score(self):
        """Without lizard installed, not_measured=True. With lizard, score 0..100."""
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_code_complexity(ctx)
        # Either not measured (no lizard) or a valid score
        if result.not_measured:
            self.assertTrue(result.not_measured)
        else:
            self.assertGreaterEqual(result.score, 0.0)
            self.assertLessEqual(result.score, 100.0)


class ChecksRegistered(unittest.TestCase):

    def test_phase5_checks_registered(self):
        _ensure_loaded()
        ids = {spec.check_id for spec in all_checks()}
        phase5_ids = {
            "git.churn_hotspots",
            "code.complexity",
        }
        self.assertTrue(phase5_ids.issubset(ids),
                        f"Missing Phase 5 checks: {phase5_ids - ids}")


class ScoreImpact(unittest.TestCase):

    def test_good_fixture_still_100_or_near(self):
        """Churn checks are not_measured for fixtures → score unchanged."""
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        specs = all_checks()
        results = [spec.fn(ctx) for spec in specs]
        for cr, spec in zip(results, specs, strict=True):
            if cr.weight == 1.0 and spec.weight != 1.0:
                cr.weight = spec.weight
        from agent_readiness.scorer import score as score_fn
        report = score_fn(ctx.root, results)
        # Should still be 100 (churn checks not_measured or 100)
        self.assertEqual(report.overall_score, 100.0)


if __name__ == "__main__":
    unittest.main()
