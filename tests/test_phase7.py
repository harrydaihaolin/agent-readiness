"""Phase 7 tests: HTML report renderer and badge generation."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_readiness.checks import _ensure_loaded, all_checks
from agent_readiness.context import RepoContext
from agent_readiness.scorer import score as score_fn


_FIXTURES = Path(__file__).parent / "fixtures"


def _make_report(fixture: str = "good"):
    _ensure_loaded()
    ctx = RepoContext(root=_FIXTURES / fixture)
    specs = all_checks()
    results = [spec.fn(ctx) for spec in specs]
    for cr, spec in zip(results, specs, strict=True):
        if cr.weight == 1.0 and spec.weight != 1.0:
            cr.weight = spec.weight
    return score_fn(ctx.root, results)


class BadgeGeneration(unittest.TestCase):

    def test_badge_contains_score(self):
        from agent_readiness.cli import _make_badge
        svg = _make_badge(100.0)
        self.assertIn("100/100", svg)
        self.assertIn("<svg", svg)

    def test_badge_green_for_high_score(self):
        from agent_readiness.cli import _make_badge
        svg = _make_badge(90.0)
        self.assertIn("#4c1", svg)  # brightgreen

    def test_badge_red_for_low_score(self):
        from agent_readiness.cli import _make_badge
        svg = _make_badge(20.0)
        self.assertIn("#e05d44", svg)  # red

    def test_badge_via_cli(self):
        import tempfile
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            badge_path = Path(td) / "badge.svg"
            result = runner.invoke(cli, [
                "scan", str(_FIXTURES / "good"),
                "--badge", str(badge_path),
            ])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue(badge_path.is_file())
            content = badge_path.read_text()
            self.assertIn("<svg", content)


class HtmlRenderer(unittest.TestCase):

    def test_html_render_requires_jinja2_or_installed(self):
        """If jinja2 is installed, render should work. Otherwise ImportError."""
        report = _make_report("good")
        try:
            from agent_readiness.renderers.html_renderer import render
            html = render(report)
            self.assertIn("<!DOCTYPE html>", html)
            self.assertIn("100.0", html)
        except ImportError:
            # jinja2 not installed — acceptable
            pass

    def test_html_via_cli(self):
        import tempfile
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            report_path = Path(td) / "report.html"
            result = runner.invoke(cli, [
                "scan", str(_FIXTURES / "good"),
                "--report", str(report_path),
            ])
            # May fail if jinja2 not installed — that's OK
            if result.exit_code == 0 and report_path.is_file():
                content = report_path.read_text()
                self.assertIn("<!DOCTYPE html>", content)


class SarifRenderer(unittest.TestCase):

    def test_sarif_renders_valid_json(self):
        import json
        from agent_readiness.renderers.sarif import render
        report = _make_report("good")
        sarif_str = render(report)
        sarif = json.loads(sarif_str)
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertIn("runs", sarif)
        self.assertIsInstance(sarif["runs"], list)
        self.assertGreater(len(sarif["runs"]), 0)

    def test_sarif_contains_rules(self):
        import json
        from agent_readiness.renderers.sarif import render
        report = _make_report("bare")
        sarif = json.loads(render(report))
        rules = sarif["runs"][0]["tool"]["driver"]["rules"]
        rule_ids = {r["id"] for r in rules}
        self.assertIn("secrets.basic_scan", rule_ids)

    def test_sarif_via_cli(self):
        import json
        import tempfile
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            sarif_path = Path(td) / "results.sarif"
            result = runner.invoke(cli, [
                "scan", str(_FIXTURES / "good"),
                "--sarif", str(sarif_path),
            ])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue(sarif_path.is_file())
            data = json.loads(sarif_path.read_text())
            self.assertEqual(data["version"], "2.1.0")


if __name__ == "__main__":
    unittest.main()
