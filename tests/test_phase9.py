"""Phase 9 tests: plugin API, SARIF export, stable contract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


_FIXTURES = Path(__file__).parent / "fixtures"


class LocalPluginLoading(unittest.TestCase):

    def test_local_plugin_registers_check(self):
        from agent_readiness.checks import _REGISTRY
        from agent_readiness.plugins import load_local_plugins

        with tempfile.TemporaryDirectory() as td:
            plugin_dir = Path(td) / ".agent_readiness_checks"
            plugin_dir.mkdir()
            plugin_code = """
from agent_readiness.checks import register
from agent_readiness.models import Pillar, CheckResult

@register(
    check_id="test.plugin_check_xyz123",
    pillar=Pillar.FLOW,
    title="Test plugin check",
    explanation="A test check from a local plugin.",
)
def check(ctx):
    return CheckResult("test.plugin_check_xyz123", Pillar.FLOW, 100.0)
"""
            (plugin_dir / "my_plugin.py").write_text(plugin_code)
            loaded = load_local_plugins(Path(td))
            self.assertEqual(len(loaded), 1)
            self.assertIn("test.plugin_check_xyz123", _REGISTRY)

        # Clean up registered check so it doesn't bleed into other tests
        _REGISTRY.pop("test.plugin_check_xyz123", None)

    def test_empty_plugin_dir_loads_nothing(self):
        from agent_readiness.plugins import load_local_plugins
        with tempfile.TemporaryDirectory() as td:
            loaded = load_local_plugins(Path(td))
        self.assertEqual(loaded, [])

    def test_missing_plugin_dir_loads_nothing(self):
        from agent_readiness.plugins import load_local_plugins
        with tempfile.TemporaryDirectory() as td:
            loaded = load_local_plugins(Path(td))
        self.assertEqual(loaded, [])


class EntryPointPluginLoading(unittest.TestCase):

    def test_entry_point_loading_returns_list(self):
        from agent_readiness.plugins import load_entry_point_plugins
        # With no installed plugins, returns empty list
        loaded = load_entry_point_plugins()
        self.assertIsInstance(loaded, list)


class SarifExport(unittest.TestCase):

    def test_sarif_schema_version(self):
        import json
        from agent_readiness.checks import _ensure_loaded, all_checks
        from agent_readiness.context import RepoContext
        from agent_readiness.scorer import score as score_fn
        from agent_readiness.renderers.sarif import render

        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        specs = all_checks()
        results = [spec.fn(ctx) for spec in specs]
        for cr, spec in zip(results, specs, strict=True):
            if cr.weight == 1.0 and spec.weight != 1.0:
                cr.weight = spec.weight
        report = score_fn(ctx.root, results)
        sarif_str = render(report)
        sarif = json.loads(sarif_str)
        self.assertEqual(sarif["version"], "2.1.0")

    def test_sarif_has_warn_findings_for_bare(self):
        import json
        from agent_readiness.checks import _ensure_loaded, all_checks
        from agent_readiness.context import RepoContext
        from agent_readiness.scorer import score as score_fn
        from agent_readiness.renderers.sarif import render

        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "bare")
        specs = all_checks()
        results = [spec.fn(ctx) for spec in specs]
        for cr, spec in zip(results, specs, strict=True):
            if cr.weight == 1.0 and spec.weight != 1.0:
                cr.weight = spec.weight
        report = score_fn(ctx.root, results)
        sarif = json.loads(render(report))
        findings = sarif["runs"][0]["results"]
        # Bare fixture has many warnings — should have SARIF results
        self.assertGreater(len(findings), 0)


class StableContract(unittest.TestCase):

    def test_report_schema_is_1(self):
        from agent_readiness.checks import _ensure_loaded, all_checks
        from agent_readiness.context import RepoContext
        from agent_readiness.scorer import score as score_fn

        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        specs = all_checks()
        results = [spec.fn(ctx) for spec in specs]
        for cr, spec in zip(results, specs, strict=True):
            if cr.weight == 1.0 and spec.weight != 1.0:
                cr.weight = spec.weight
        report = score_fn(ctx.root, results)
        self.assertEqual(report.schema, 1)

    def test_report_to_dict_has_required_keys(self):
        from agent_readiness.checks import _ensure_loaded, all_checks
        from agent_readiness.context import RepoContext
        from agent_readiness.scorer import score as score_fn

        _ensure_loaded()
        ctx = RepoContext(root=_FIXTURES / "good")
        specs = all_checks()
        results = [spec.fn(ctx) for spec in specs]
        report = score_fn(ctx.root, results)
        d = report.to_dict()
        for key in ("schema", "repo_path", "overall_score", "pillars"):
            self.assertIn(key, d)

    def test_explain_in_json_via_cli(self):
        """--json output includes explanation text on every check dict."""
        import json
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["scan", str(_FIXTURES / "good"), "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output)
        self.assertEqual(data["schema"], 1)
        checks = [c for p in data["pillars"] for c in p["checks"]]
        self.assertGreater(len(checks), 0)
        for c in checks:
            self.assertIn("explanation", c, f"missing explanation on {c['check_id']}")
            self.assertIsInstance(c["explanation"], str)
            self.assertGreater(len(c["explanation"]), 0)

    def test_score_impact_in_json_via_cli(self):
        """--json output includes score_impact on every check dict."""
        import json
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["scan", str(_FIXTURES / "good"), "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output)
        checks = [c for p in data["pillars"] for c in p["checks"]]
        for c in checks:
            self.assertIn("score_impact", c, f"missing score_impact on {c['check_id']}")


if __name__ == "__main__":
    unittest.main()
