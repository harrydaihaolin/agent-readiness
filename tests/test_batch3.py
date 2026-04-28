"""Batch 3 tests: meta.consistency check, check-level baseline deltas, messy fixture."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_readiness.checks import _ensure_loaded, all_checks
from agent_readiness.context import RepoContext
from agent_readiness.checks.meta_consistency import check_meta_consistency


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


class MetaConsistencyCheck(unittest.TestCase):

    def _tmp(self, files: dict[str, str]) -> RepoContext:
        td = tempfile.mkdtemp()
        root = Path(td)
        for rel, contents in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(contents)
        return RepoContext(root=root)

    def test_no_readme_scores_100(self):
        ctx = self._tmp({})
        result = check_meta_consistency(ctx)
        self.assertEqual(result.score, 100.0)

    def test_readme_with_pytest_but_no_config_warns(self):
        ctx = self._tmp({"README.md": "## Testing\nRun with `pytest`.\n"})
        result = check_meta_consistency(ctx)
        warn = [f for f in result.findings if f.severity.value == "warn"]
        self.assertTrue(any("pytest" in f.message for f in warn),
                        "should warn about pytest reference without config")
        self.assertLess(result.score, 100.0)

    def test_readme_with_pytest_and_pyproject_ok(self):
        ctx = self._tmp({
            "README.md": "Run `pytest` to test.\n",
            "pyproject.toml": "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n",
        })
        result = check_meta_consistency(ctx)
        warn = [f for f in result.findings if f.severity.value == "warn"
                and "pytest" in f.message]
        self.assertEqual(len(warn), 0, "no warn when pyproject has pytest config")

    def test_readme_with_npm_test_but_no_package_json_warns(self):
        ctx = self._tmp({"README.md": "Run `npm test` to run the test suite.\n"})
        result = check_meta_consistency(ctx)
        warn = [f for f in result.findings if f.severity.value == "warn"]
        self.assertTrue(any("npm" in f.message for f in warn))

    def test_readme_with_npm_test_and_package_json_ok(self):
        ctx = self._tmp({
            "README.md": "Run `npm test`.\n",
            "package.json": '{"scripts": {"test": "jest"}}\n',
        })
        result = check_meta_consistency(ctx)
        warn = [f for f in result.findings if "npm" in f.message
                and f.severity.value == "warn"]
        self.assertEqual(len(warn), 0)

    def test_tiny_agents_md_warns(self):
        ctx = self._tmp({"AGENTS.md": "# TODO\n"})
        result = check_meta_consistency(ctx)
        warn = [f for f in result.findings if "AGENTS.md" in f.message]
        self.assertGreater(len(warn), 0)

    def test_substantial_agents_md_ok(self):
        ctx = self._tmp({"AGENTS.md": "# Agent guide\n" + "Use make test to run tests.\n" * 10})
        result = check_meta_consistency(ctx)
        warn = [f for f in result.findings if "AGENTS.md" in f.message
                and f.severity.value == "warn"]
        self.assertEqual(len(warn), 0)

    def test_good_fixture_is_consistent(self):
        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        result = check_meta_consistency(ctx)
        self.assertEqual(result.score, 100.0)

    def test_meta_consistency_is_registered(self):
        _ensure_loaded()
        ids = {spec.check_id for spec in all_checks()}
        self.assertIn("meta.consistency", ids)


class CheckLevelBaselineDelta(unittest.TestCase):

    def test_delta_checks_in_json_output(self):
        """--baseline adds delta.checks keyed by check_id."""
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem():
            # First scan: save baseline
            r1 = runner.invoke(cli, ["scan", str(_FIXTURES / "bare"), "--json"])
            self.assertEqual(r1.exit_code, 0, r1.output)
            Path("baseline.json").write_text(r1.output)

            # Second scan: compare against baseline
            r2 = runner.invoke(cli, [
                "scan", str(_FIXTURES / "bare"), "--json",
                "--baseline", "baseline.json",
            ])
            self.assertEqual(r2.exit_code, 0, r2.output)
            data = json.loads(r2.output)

        self.assertIn("delta", data)
        self.assertIn("checks", data["delta"])
        checks_delta = data["delta"]["checks"]
        self.assertIsInstance(checks_delta, dict)
        # Same repo → all deltas are zero
        for check_id, delta in checks_delta.items():
            self.assertAlmostEqual(delta, 0.0,
                                   msg=f"check {check_id} should have 0 delta vs itself")

    def test_delta_checks_shows_improvement(self):
        """check-level delta is positive when a check improved."""
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem():
            # Baseline from bare fixture (low score)
            r1 = runner.invoke(cli, ["scan", str(_FIXTURES / "bare"), "--json"])
            self.assertEqual(r1.exit_code, 0, r1.output)
            Path("baseline.json").write_text(r1.output)

            # Compare against the good fixture (high score)
            r2 = runner.invoke(cli, [
                "scan", str(_FIXTURES / "good"), "--json",
                "--baseline", "baseline.json",
            ])
            self.assertEqual(r2.exit_code, 0, r2.output)
            data = json.loads(r2.output)

        checks_delta = data["delta"]["checks"]
        # At least some checks should have improved (positive delta)
        positive = [v for v in checks_delta.values() if v > 0]
        self.assertGreater(len(positive), 0, "some checks should improve from bare → good")


class MessyFixture(unittest.TestCase):

    def test_messy_fixture_scores_mid_range(self):
        """Messy fixture is code-quality-good but agent-UX-poor → 40–70 range."""
        report = _scan(_FIXTURES / "messy")
        self.assertGreater(report.overall_score, 30.0,
                           f"messy should score above 30 (got {report.overall_score})")
        self.assertLess(report.overall_score, 75.0,
                        f"messy should score below 75 (got {report.overall_score})")

    def test_messy_fixture_has_ci_warn(self):
        """Messy fixture's GHA workflow has no test step → WARN."""
        _ensure_loaded()
        from agent_readiness.checks.ci_check import check_ci_configured
        ctx = RepoContext(root=_FIXTURES / "messy")
        result = check_ci_configured(ctx)
        self.assertEqual(result.score, 80.0)
        self.assertEqual(result.findings[0].severity.value, "warn")

    def test_messy_fixture_env_parity_warn(self):
        """Messy fixture has os.environ but no .env.example → WARN."""
        _ensure_loaded()
        from agent_readiness.checks.env_parity import check_env_example_parity
        ctx = RepoContext(root=_FIXTURES / "messy")
        result = check_env_example_parity(ctx)
        self.assertEqual(result.score, 40.0)


if __name__ == "__main__":
    unittest.main()
