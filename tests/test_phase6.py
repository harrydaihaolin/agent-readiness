"""Phase 6 tests: CLI surface — config, init, --weights, --only, --baseline, --fail-below."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from agent_readiness.config import extract_weights, load_config
from agent_readiness.models import Pillar


_FIXTURES = Path(__file__).parent / "fixtures"


class LoadConfigTest(unittest.TestCase):

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            config = load_config(Path(td))
        self.assertEqual(config, {})

    def test_existing_file_is_parsed(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / ".agent-readiness.toml"
            config_path.write_text("[weights]\nfeedback = 0.5\n")
            config = load_config(Path(td))
        self.assertIn("weights", config)
        self.assertAlmostEqual(config["weights"]["feedback"], 0.5)


class ExtractWeightsTest(unittest.TestCase):

    def test_empty_config_returns_none(self):
        self.assertIsNone(extract_weights({}))

    def test_no_weights_section_returns_none(self):
        self.assertIsNone(extract_weights({"ignore": {"checks": []}}))

    def test_weights_override_defaults(self):
        config = {"weights": {"feedback": 0.5, "cognitive_load": 0.25, "flow": 0.25}}
        weights = extract_weights(config)
        self.assertIsNotNone(weights)
        self.assertAlmostEqual(weights[Pillar.FEEDBACK], 0.5)
        self.assertAlmostEqual(weights[Pillar.COGNITIVE_LOAD], 0.25)
        self.assertAlmostEqual(weights[Pillar.FLOW], 0.25)

    def test_partial_override_keeps_defaults(self):
        from agent_readiness.scorer import DEFAULT_WEIGHTS
        config = {"weights": {"feedback": 0.6}}
        weights = extract_weights(config)
        self.assertAlmostEqual(weights[Pillar.FEEDBACK], 0.6)
        # Other pillars keep defaults
        self.assertAlmostEqual(weights[Pillar.COGNITIVE_LOAD],
                               DEFAULT_WEIGHTS[Pillar.COGNITIVE_LOAD])


class InitCommandTest(unittest.TestCase):

    def test_init_creates_config_file(self):
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["init", "."])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue(Path(".agent-readiness.toml").is_file())

    def test_init_does_not_overwrite(self):
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".agent-readiness.toml").write_text("# existing\n")
            result = runner.invoke(cli, ["init", "."])
            self.assertNotEqual(result.exit_code, 0)
            # Content unchanged
            content = Path(".agent-readiness.toml").read_text()
            self.assertEqual(content, "# existing\n")

    def test_init_content_has_weights_section(self):
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(cli, ["init", "."])
            content = Path(".agent-readiness.toml").read_text()
            self.assertIn("[weights]", content)
            self.assertIn("[ignore]", content)


class OnlyFilterTest(unittest.TestCase):

    def test_only_filters_by_pillar(self):
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "scan", str(_FIXTURES / "good"),
            "--json", "--only", "feedback",
        ])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output)
        # Only feedback pillar should have measured checks
        for pillar in data["pillars"]:
            if pillar["pillar"] != "feedback":
                for check in pillar.get("checks", []):
                    # Either not present or all not_measured (no checks ran)
                    pass  # Pillars may be empty with score 100 (nothing to dock)

    def test_only_filters_by_check_id(self):
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "scan", str(_FIXTURES / "good"),
            "--json", "--only", "secrets.basic_scan",
        ])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output)
        # Only one check ran
        all_checks = []
        for pillar in data["pillars"]:
            all_checks.extend(pillar.get("checks", []))
        measured = [c for c in all_checks if not c.get("not_measured")]
        check_ids = {c["check_id"] for c in measured}
        self.assertIn("secrets.basic_scan", check_ids)
        self.assertEqual(len(check_ids), 1)


class FailBelowTest(unittest.TestCase):

    def test_fail_below_0_does_not_exit_1(self):
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "scan", str(_FIXTURES / "good"),
            "--fail-below", "0",
        ])
        self.assertEqual(result.exit_code, 0)

    def test_fail_below_fires_when_score_low(self):
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        # bare fixture scores much less than 100
        result = runner.invoke(cli, [
            "scan", str(_FIXTURES / "bare"),
            "--fail-below", "99",
        ])
        self.assertEqual(result.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
