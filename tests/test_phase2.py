"""Phase 2 tests: manifest, lockfile, git history checks."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_readiness.checks import _ensure_loaded, all_checks
from agent_readiness.context import RepoContext
from agent_readiness.checks.manifest import check_manifest_detected, check_lockfile_present
from agent_readiness.checks.git_history import check_git_has_history


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


class ManifestDetectedCheck(unittest.TestCase):

    def test_good_fixture_has_manifest(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_manifest_detected(ctx)
        self.assertEqual(result.score, 100.0)
        self.assertEqual(result.check_id, "manifest.detected")

    def test_bare_fixture_no_manifest(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_manifest_detected(ctx)
        self.assertEqual(result.score, 0.0)

    def test_bare_has_warn_finding(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_manifest_detected(ctx)
        from agent_readiness.models import Severity
        self.assertTrue(any(f.severity == Severity.WARN for f in result.findings))


class LockfileCheck(unittest.TestCase):

    def test_good_fixture_has_lockfile(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_lockfile_present(ctx)
        self.assertEqual(result.score, 100.0)

    def test_bare_fixture_no_lockfile(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_lockfile_present(ctx)
        self.assertEqual(result.score, 0.0)


class GitHistoryCheck(unittest.TestCase):

    def test_both_fixtures_in_outer_git(self):
        """Both fixtures live inside the outer git repo which has many commits."""
        _ensure_loaded()
        for fixture in ("good", "bare"):
            ctx = RepoContext(root=_FIXTURES / fixture)
            result = check_git_has_history(ctx)
            self.assertGreaterEqual(result.score, 70.0,
                                    f"{fixture} fixture should score >=70 for git history")

    def test_check_id_correct(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_git_has_history(ctx)
        self.assertEqual(result.check_id, "git.has_history")


class ChecksRegistered(unittest.TestCase):

    def test_phase2_checks_registered(self):
        _ensure_loaded()
        ids = {spec.check_id for spec in all_checks()}
        phase2_ids = {
            "manifest.detected",
            "manifest.lockfile_present",
            "git.has_history",
        }
        self.assertTrue(phase2_ids.issubset(ids),
                        f"Missing Phase 2 checks: {phase2_ids - ids}")


if __name__ == "__main__":
    unittest.main()
