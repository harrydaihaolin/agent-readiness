"""Tests for src/agent_readiness/rules_eval/ and the vendored rules_pack.

Covers:
- The five OSS matchers run correctly on synthetic mini-repos
- The loader gates on rules_version
- The vendored pack is present and loadable end-to-end
"""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import (
    LoadedRule,
    RuleLoadError,
    evaluate_rules,
    load_rules_from_dir,
)
from agent_readiness.rules_eval.evaluator import evaluate_rule
from agent_readiness.rules_eval.loader import load_rule_file
from agent_readiness.rules_eval.matchers import (
    match_command_in_makefile,
    match_file_size,
    match_manifest_field,
    match_path_glob,
    match_regex_in_files,
)
from agent_readiness.rules_pack_loader import default_rules_dir


def _make_ctx(tmpdir: Path, files: dict[str, str]) -> RepoContext:
    for rel, content in files.items():
        p = tmpdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return RepoContext(root=tmpdir)


class TestFileSizeMatcher(unittest.TestCase):
    def test_no_findings_under_threshold(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"a.py": "print('hi')\n"})
            findings = match_file_size(ctx, {"threshold_lines": 500, "threshold_bytes": 51200, "exclude_globs": []})
            self.assertEqual(findings, [])

    def test_fires_on_large_file(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"big.py": "x = 1\n" * 600})
            findings = match_file_size(ctx, {"threshold_lines": 500, "threshold_bytes": 51200, "exclude_globs": []})
            self.assertTrue(findings)
            self.assertIn("big.py", findings[0][0])

    def test_excludes(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"big.lock": "x\n" * 600})
            findings = match_file_size(ctx, {"threshold_lines": 500, "threshold_bytes": 51200, "exclude_globs": ["*.lock"]})
            self.assertEqual(findings, [])


class TestPathGlobMatcher(unittest.TestCase):
    def test_required_present(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"AGENTS.md": "x"})
            findings = match_path_glob(ctx, {"require_globs": ["AGENTS.md"], "forbid_globs": []})
            self.assertEqual(findings, [])

    def test_required_missing(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"README.md": "x"})
            findings = match_path_glob(ctx, {"require_globs": ["AGENTS.md"], "forbid_globs": []})
            self.assertEqual(len(findings), 1)

    def test_forbidden_present(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {".env": "SECRET=x"})
            findings = match_path_glob(ctx, {"require_globs": [], "forbid_globs": [".env"]})
            self.assertEqual(len(findings), 1)


class TestManifestFieldMatcher(unittest.TestCase):
    def test_pyproject_field_missing(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"pyproject.toml": "[project]\nname='x'\nversion='0'"})
            findings = match_manifest_field(
                ctx,
                {"manifest": "pyproject.toml", "field_path": "project.scripts", "fire_when": "missing"},
            )
            self.assertEqual(len(findings), 1)

    def test_pyproject_field_present(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"pyproject.toml": "[project]\nname='x'\nversion='0'\n[project.scripts]\nx='m:f'"})
            findings = match_manifest_field(
                ctx,
                {"manifest": "pyproject.toml", "field_path": "project.scripts", "fire_when": "missing"},
            )
            self.assertEqual(findings, [])

    def test_manifest_missing(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"README.md": ""})
            findings = match_manifest_field(
                ctx,
                {"manifest": "pyproject.toml", "field_path": "project.scripts", "fire_when": "missing"},
            )
            self.assertEqual(len(findings), 1)


class TestRegexInFilesMatcher(unittest.TestCase):
    def test_match_fires(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"src/a.py": "import os\nx = os.environ['X']\n"})
            findings = match_regex_in_files(
                ctx,
                {"pattern": r"os\.environ", "file_globs": ["src/**/*.py"], "fire_when": "match"},
            )
            self.assertTrue(findings)

    def test_no_match_fires_when_expected(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"src/a.py": "x = 1\n"})
            findings = match_regex_in_files(
                ctx,
                {"pattern": r"# TODO", "file_globs": ["src/**/*.py"], "fire_when": "no_match"},
            )
            self.assertEqual(len(findings), 1)


class TestCommandInMakefileMatcher(unittest.TestCase):
    def test_target_present(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"Makefile": "test:\n\techo hi\n"})
            findings = match_command_in_makefile(ctx, {"target": "test", "fire_when": "missing"})
            self.assertEqual(findings, [])

    def test_target_missing(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"Makefile": "lint:\n\techo hi\n"})
            findings = match_command_in_makefile(ctx, {"target": "test", "fire_when": "missing"})
            self.assertEqual(len(findings), 1)

    def test_makefile_missing(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"README.md": ""})
            findings = match_command_in_makefile(ctx, {"target": "test", "fire_when": "missing"})
            self.assertEqual(len(findings), 1)


class TestLoaderVersionGating(unittest.TestCase):
    def test_supported_version_loads(self):
        with TemporaryDirectory() as td:
            yaml_text = textwrap.dedent("""
                rules_version: 1
                id: x.test
                pillar: flow
                title: t
                weight: 1.0
                severity: warn
                explanation: e
                match:
                  type: path_glob
                  require_globs: [AGENTS.md]
            """)
            (Path(td) / "x.yaml").write_text(yaml_text)
            rules = load_rules_from_dir(Path(td))
            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0].rule_id, "x.test")

    def test_unsupported_version_skipped(self):
        with TemporaryDirectory() as td:
            yaml_text = textwrap.dedent("""
                rules_version: 99
                id: future.rule
                pillar: flow
                title: t
                match:
                  type: path_glob
                  require_globs: [X]
            """)
            (Path(td) / "x.yaml").write_text(yaml_text)
            rules = load_rules_from_dir(Path(td))
            self.assertEqual(rules, [])

    def test_missing_version_raises(self):
        with TemporaryDirectory() as td:
            yaml_text = "id: x\npillar: flow\nmatch: {type: path_glob}\n"
            (Path(td) / "x.yaml").write_text(yaml_text)
            with self.assertRaises(RuleLoadError):
                load_rule_file(Path(td) / "x.yaml")


class TestEvaluatorUnknownMatchType(unittest.TestCase):
    def test_unknown_match_type_marks_not_measured(self):
        rule = LoadedRule(
            rule_id="x.advanced",
            pillar="flow",
            title="advanced",
            weight=1.0,
            severity="warn",
            explanation="",
            match={"type": "ast_query", "node": "FunctionDef"},
            fix_hint=None,
            insight_query=None,
            source_path=Path("/dev/null"),
        )
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"a.py": "x = 1"})
            cr = evaluate_rule(rule, ctx)
        self.assertTrue(cr.not_measured)
        self.assertEqual(cr.findings, [])


class TestVendoredPackSmoke(unittest.TestCase):
    def test_default_rules_dir_resolves(self):
        rd = default_rules_dir()
        self.assertIsNotNone(rd, "vendored rules_pack/ not found; run scripts/vendor_rules.sh v1.0.0")
        self.assertTrue(rd.is_dir())

    def test_vendored_pack_loads_seven_rules(self):
        rd = default_rules_dir()
        loaded = load_rules_from_dir(rd)
        # We know v1.0.0 ships 7 rules.
        self.assertEqual(len(loaded), 7)

    def test_vendored_pack_evaluates_on_self(self):
        rd = default_rules_dir()
        loaded = load_rules_from_dir(rd)
        # Evaluate against the rules_pack directory itself; we don't assert
        # specific findings, just that it runs end-to-end without raising.
        ctx = RepoContext(root=Path(rd))
        results = evaluate_rules(loaded, ctx)
        self.assertEqual(len(results), len(loaded))


if __name__ == "__main__":
    unittest.main()
