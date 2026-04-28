"""Phase 3.5 tests: flow completeness checks."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_readiness.checks import _ensure_loaded, all_checks
from agent_readiness.context import RepoContext
from agent_readiness.checks.entry_points import check_entry_points_detected
from agent_readiness.checks.env_parity import check_env_example_parity
from agent_readiness.checks.ci_check import check_ci_configured
from agent_readiness.checks.setup_steps import check_setup_command_count
from agent_readiness.checks.naming import check_naming_search_precision


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


class EntryPointsCheck(unittest.TestCase):

    def test_good_fixture_has_entry_point(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_entry_points_detected(ctx)
        self.assertEqual(result.score, 100.0)

    def test_bare_fixture_no_entry_point(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_entry_points_detected(ctx)
        self.assertEqual(result.score, 0.0)


class EnvParityCheck(unittest.TestCase):

    def test_good_fixture_no_env_refs_or_example_exists(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_env_example_parity(ctx)
        self.assertEqual(result.score, 100.0)

    def test_bare_fixture_no_env_refs(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_env_example_parity(ctx)
        self.assertEqual(result.score, 100.0)


class CiConfiguredCheck(unittest.TestCase):

    def test_good_fixture_has_ci(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_ci_configured(ctx)
        self.assertEqual(result.score, 100.0)
        # Most-specific detector wins: GHA workflow → message names it.
        self.assertIn("GitHub Actions", result.findings[0].message)

    def test_bare_fixture_no_ci(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_ci_configured(ctx)
        self.assertEqual(result.score, 0.0)

    def _scan_tmp(self, files: dict[str, str]):
        """Spin up a tmp dir with the given files and run the check.

        ``files`` maps relative path → contents. Returns the CheckResult.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel, contents in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)
            ctx = RepoContext(root=root)
            return check_ci_configured(ctx)

    def test_earthfile_detected(self):
        """Regression: Earthly Earthfile must register as CI.

        Reported by users running large monorepos where the Earthfile is
        the in-repo build/test recipe and the trigger lives outside the
        tracked repo. Pre-fix this returned score=0 with "No CI found".
        """
        result = self._scan_tmp({"Earthfile": "VERSION 0.7\nFROM alpine\n"})
        self.assertEqual(result.score, 100.0)
        self.assertIn("Earthly", result.findings[0].message)

    def test_drone_yaml_detected(self):
        result = self._scan_tmp({".drone.yaml": "kind: pipeline\n"})
        self.assertEqual(result.score, 100.0)
        self.assertIn("Drone", result.findings[0].message)

    def test_woodpecker_dir_detected(self):
        result = self._scan_tmp(
            {".woodpecker/test.yml": "steps:\n  - name: test\n"}
        )
        self.assertEqual(result.score, 100.0)
        self.assertIn("Woodpecker", result.findings[0].message)

    def test_gha_takes_precedence_over_earthfile(self):
        """When both exist, the most specific (trigger) detector wins.

        Order matters only for the message; both score 100.
        """
        result = self._scan_tmp({
            "Earthfile": "VERSION 0.7\n",
            ".github/workflows/ci.yml": "name: ci\non: [push]\n",
        })
        self.assertEqual(result.score, 100.0)
        self.assertIn("GitHub Actions", result.findings[0].message)


class SetupCommandCountCheck(unittest.TestCase):

    def test_good_fixture_few_commands(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_setup_command_count(ctx)
        # Good fixture has make install in setup section → 1 command → 100
        self.assertEqual(result.score, 100.0)

    def test_bare_fixture_no_setup_section(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_setup_command_count(ctx)
        # Bare has no code blocks in setup → 100
        self.assertEqual(result.score, 100.0)


class NamingCheck(unittest.TestCase):

    def test_good_fixture_no_ambiguous_names(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_naming_search_precision(ctx)
        self.assertEqual(result.score, 100.0)

    def test_bare_fixture_no_ambiguous_names(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        result = check_naming_search_precision(ctx)
        self.assertEqual(result.score, 100.0)


class ChecksRegistered(unittest.TestCase):

    def test_phase35_checks_registered(self):
        _ensure_loaded()
        ids = {spec.check_id for spec in all_checks()}
        phase35_ids = {
            "entry_points.detected",
            "env.example_parity",
            "ci.configured",
            "setup.command_count",
            "naming.search_precision",
        }
        self.assertTrue(phase35_ids.issubset(ids),
                        f"Missing Phase 3.5 checks: {phase35_ids - ids}")


class ScoreImpact(unittest.TestCase):

    def test_good_fixture_scores_100(self):
        report = _scan(_FIXTURES / "good")
        self.assertEqual(report.overall_score, 100.0)

    def test_bare_fixture_scores_below_60(self):
        report = _scan(_FIXTURES / "bare")
        self.assertLess(report.overall_score, 60.0)

    def test_score_gap_above_50(self):
        good = _scan(_FIXTURES / "good").overall_score
        bare = _scan(_FIXTURES / "bare").overall_score
        self.assertGreater(good - bare, 50.0)


if __name__ == "__main__":
    unittest.main()
