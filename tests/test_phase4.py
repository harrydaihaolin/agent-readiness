"""Phase 4 tests: feedback signals — typecheck, lint, gitignore."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_readiness.checks import _ensure_loaded, all_checks
from agent_readiness.context import RepoContext
from agent_readiness.checks.typecheck import check_typecheck_configured
from agent_readiness.checks.lint_check import check_lint_configured
from agent_readiness.checks.gitignore import check_gitignore_covers_junk


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


class TypecheckCheck(unittest.TestCase):

    def test_good_fixture_has_typecheck(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_typecheck_configured(ctx)
        self.assertEqual(result.score, 100.0)

    def test_bare_fixture_no_typecheck(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_typecheck_configured(ctx)
        self.assertEqual(result.score, 0.0)


class LintCheck(unittest.TestCase):

    def test_good_fixture_has_lint(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_lint_configured(ctx)
        self.assertEqual(result.score, 100.0)

    def test_bare_fixture_no_lint(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_lint_configured(ctx)
        self.assertEqual(result.score, 0.0)


class GitignoreCheck(unittest.TestCase):

    def test_good_fixture_has_gitignore(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_gitignore_covers_junk(ctx)
        self.assertEqual(result.score, 100.0)

    def test_bare_fixture_no_gitignore(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_gitignore_covers_junk(ctx)
        self.assertEqual(result.score, 0.0)

    def test_bare_has_warn_finding(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_gitignore_covers_junk(ctx)
        from agent_readiness.models import Severity
        self.assertTrue(any(f.severity == Severity.WARN for f in result.findings))


class ChecksRegistered(unittest.TestCase):

    def test_phase4_checks_registered(self):
        _ensure_loaded()
        ids = {spec.check_id for spec in all_checks()}
        phase4_ids = {
            "typecheck.configured",
            "lint.configured",
            "gitignore.covers_junk",
        }
        self.assertTrue(phase4_ids.issubset(ids),
                        f"Missing Phase 4 checks: {phase4_ids - ids}")


class ScoreImpact(unittest.TestCase):

    def test_good_fixture_still_100(self):
        report = _scan(_FIXTURES / "good")
        self.assertEqual(report.overall_score, 100.0)

    def test_bare_still_below_60(self):
        report = _scan(_FIXTURES / "bare")
        self.assertLess(report.overall_score, 60.0)

    def test_gap_above_50(self):
        good = _scan(_FIXTURES / "good").overall_score
        bare = _scan(_FIXTURES / "bare").overall_score
        self.assertGreater(good - bare, 50.0)

    def test_bare_safety_not_100_with_gitignore(self):
        """Bare has no .gitignore so Safety should not be 100."""
        report = _scan(_FIXTURES / "bare")
        from agent_readiness.models import Pillar
        by_pillar = {p.pillar: p.score for p in report.pillar_scores}
        self.assertLess(by_pillar[Pillar.SAFETY], 100.0)


if __name__ == "__main__":
    unittest.main()
