"""Phase 3 tests: context-window economics, repo-shape checks."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_readiness.checks import _ensure_loaded, all_checks
from agent_readiness.context import RepoContext
from agent_readiness.checks.repo_shape import (
    check_top_level_count,
    check_large_files,
    check_token_budget,
)


_FIXTURES = Path(__file__).parent / "fixtures"


def _scan(repo: Path):
    _ensure_loaded()
    ctx = RepoContext(root=repo)
    specs = all_checks()
    results = [spec.fn(ctx) for spec in specs]
    for cr, spec in zip(results, specs, strict=True):
        if cr.weight == 1.0 and spec.weight != 1.0:
            cr.weight = spec.weight
    from agent_readiness.scorer import score
    return score(ctx.root, results)


class TopLevelCountCheck(unittest.TestCase):

    def test_good_fixture_few_files(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_top_level_count(ctx)
        self.assertEqual(result.score, 100.0)

    def test_bare_fixture_few_files(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_top_level_count(ctx)
        # bare has 1 file → score 100
        self.assertEqual(result.score, 100.0)

    def test_weight_is_0_8(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_top_level_count(ctx)
        self.assertEqual(result.weight, 0.8)


class LargeFilesCheck(unittest.TestCase):

    def test_good_fixture_no_large_files(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_large_files(ctx)
        self.assertEqual(result.score, 100.0)

    def test_bare_fixture_no_large_files(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_large_files(ctx)
        self.assertEqual(result.score, 100.0)


class TokenBudgetCheck(unittest.TestCase):

    def test_good_fixture_small_token_budget(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_token_budget(ctx)
        # Small fixture — should be well under 8k tokens
        self.assertGreaterEqual(result.score, 80.0)

    def test_bare_fixture_small_token_budget(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_token_budget(ctx)
        self.assertGreaterEqual(result.score, 80.0)

    def test_custom_warn_threshold_lowers_score(self):
        """Configuring a very low token_budget_warn triggers WARN on a small fixture."""
        _ensure_loaded()
        # Set warn threshold to 1 token so even a tiny repo triggers WARN
        ctx = RepoContext(root=_FIXTURES / "bare",
                         context_config={"token_budget_warn": 1, "token_budget_max": 80_000})
        result = check_token_budget(ctx)
        self.assertLess(result.score, 100.0)
        warn_findings = [f for f in result.findings if f.severity.value == "warn"]
        self.assertGreater(len(warn_findings), 0)


class ChecksRegistered(unittest.TestCase):

    def test_phase3_checks_registered(self):
        _ensure_loaded()
        ids = {spec.check_id for spec in all_checks()}
        phase3_ids = {
            "repo_shape.top_level_count",
            "repo_shape.large_files",
            "repo_shape.token_budget",
        }
        self.assertTrue(phase3_ids.issubset(ids),
                        f"Missing Phase 3 checks: {phase3_ids - ids}")


class ScoreImpact(unittest.TestCase):

    def test_good_fixture_cog_load_high(self):
        report = _scan(_FIXTURES / "good")
        from agent_readiness.models import Pillar
        by_pillar = {p.pillar: p.score for p in report.pillar_scores}
        # All CogLoad checks score 100 → overall CogLoad should be 100
        self.assertEqual(by_pillar[Pillar.COGNITIVE_LOAD], 100.0)

    def test_overall_score_at_least_95(self):
        report = _scan(_FIXTURES / "good")
        self.assertGreaterEqual(report.overall_score, 95.0)


if __name__ == "__main__":
    unittest.main()
