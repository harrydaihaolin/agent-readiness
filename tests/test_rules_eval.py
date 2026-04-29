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
    OssMatchTypeRegistry,
    RuleLoadError,
    evaluate_rules,
    load_rules_from_dir,
    register_private_matcher,
    unregister_private_matcher,
)
from agent_readiness.rules_eval.evaluator import evaluate_rule
from agent_readiness.rules_eval.loader import load_rule_file
from agent_readiness.rules_eval.matchers import (
    match_command_in_makefile,
    match_composite,
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


class TestCompositeMatcher(unittest.TestCase):
    """Composite (and / or / not) over leaf matchers."""

    def test_and_fires_when_all_clauses_fire(self):
        # env-parity: code reads env vars AND .env.example missing → fire
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"src/a.py": "import os\nx=os.environ['X']\n"})
            cfg = {
                "type": "composite",
                "op": "and",
                "summary": "env reads but no .env.example",
                "clauses": [
                    {"type": "regex_in_files", "pattern": r"os\.environ",
                     "file_globs": ["src/**/*.py"], "fire_when": "match"},
                    {"type": "path_glob", "require_globs": [".env.example"]},
                ],
            }
            findings = match_composite(ctx, cfg)
            self.assertEqual(len(findings), 1)
            self.assertIn("env reads", findings[0][2])

    def test_and_silent_when_any_clause_silent(self):
        # env reads exist but .env.example is present → AND should NOT fire
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {
                "src/a.py": "import os\nx=os.environ['X']\n",
                ".env.example": "X=\n",
            })
            cfg = {
                "type": "composite",
                "op": "and",
                "clauses": [
                    {"type": "regex_in_files", "pattern": r"os\.environ",
                     "file_globs": ["src/**/*.py"], "fire_when": "match"},
                    {"type": "path_glob", "require_globs": [".env.example"]},
                ],
            }
            self.assertEqual(match_composite(ctx, cfg), [])

    def test_or_fires_per_clause(self):
        # Either Makefile target test OR pyproject pytest config OR Justfile
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"README.md": ""})
            cfg = {
                "type": "composite",
                "op": "or",
                "clauses": [
                    {"type": "command_in_makefile", "target": "test", "fire_when": "missing"},
                    {"type": "manifest_field", "manifest": "pyproject.toml",
                     "field_path": "tool.pytest.ini_options", "fire_when": "missing"},
                    {"type": "path_glob", "require_globs": ["Justfile"]},
                ],
            }
            findings = match_composite(ctx, cfg)
            # All three sub-clauses should fire (nothing exists), so OR returns 3.
            self.assertEqual(len(findings), 3)

    def test_or_silent_when_no_clause_fires(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {
                "Makefile": "test:\n\techo hi\n",
                "pyproject.toml": "[tool.pytest.ini_options]\nminversion='6'\n",
                "Justfile": "test:\n  echo\n",
            })
            cfg = {
                "type": "composite",
                "op": "or",
                "clauses": [
                    {"type": "command_in_makefile", "target": "test", "fire_when": "missing"},
                    {"type": "manifest_field", "manifest": "pyproject.toml",
                     "field_path": "tool.pytest.ini_options", "fire_when": "missing"},
                    {"type": "path_glob", "require_globs": ["Justfile"]},
                ],
            }
            self.assertEqual(match_composite(ctx, cfg), [])

    def test_not_fires_when_inner_silent(self):
        # `not` is the standard "X is missing" — fires when require_globs
        # produces NO findings (i.e. AGENTS.md is present).
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"AGENTS.md": "x"})
            cfg = {
                "type": "composite",
                "op": "not",
                "summary": "AGENTS.md present (rule expected absent)",
                "clauses": [
                    {"type": "path_glob", "require_globs": ["AGENTS.md"]},
                ],
            }
            findings = match_composite(ctx, cfg)
            self.assertEqual(len(findings), 1)
            self.assertIn("AGENTS.md", findings[0][2])

    def test_not_silent_when_inner_fires(self):
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"README.md": ""})
            cfg = {
                "type": "composite",
                "op": "not",
                "clauses": [
                    {"type": "path_glob", "require_globs": ["AGENTS.md"]},
                ],
            }
            self.assertEqual(match_composite(ctx, cfg), [])

    def test_recursion_capped(self):
        # Deeply nested composite of trivially-firing clauses still terminates.
        cfg = {"type": "composite", "op": "or",
               "clauses": [{"type": "path_glob", "require_globs": ["AGENTS.md"]}]}
        for _ in range(10):
            cfg = {"type": "composite", "op": "or", "clauses": [cfg]}
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"README.md": ""})
            # Should not raise; at depth > _COMPOSITE_MAX_DEPTH the deepest
            # call returns [], which then propagates out to []
            match_composite(ctx, cfg)


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


class TestPrivateMatcherRegistration(unittest.TestCase):
    """Downstream engines (e.g. agent-readiness-pro) can register
    private match types; the OSS evaluator dispatches to them. Built-in
    OSS types cannot be overridden."""

    def setUp(self):
        # Each test must clean up after itself; the registry is module-level.
        self._snapshot = set(OssMatchTypeRegistry.keys())

    def tearDown(self):
        # Drop anything the test added.
        added = set(OssMatchTypeRegistry.keys()) - self._snapshot
        for name in added:
            OssMatchTypeRegistry.pop(name, None)

    def test_register_and_dispatch(self):
        def _fake_ast_query(ctx, cfg):
            node = cfg.get("node", "?")
            return [(None, None, f"ast_query node={node} fired (fake)")]

        register_private_matcher("ast_query", _fake_ast_query)

        rule = LoadedRule(
            rule_id="pro.ast_demo", pillar="flow", title="demo",
            weight=1.0, severity="warn", explanation="",
            match={"type": "ast_query", "node": "FunctionDef"},
            fix_hint=None, insight_query=None, source_path=Path("/dev/null"),
        )
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"a.py": "x = 1"})
            cr = evaluate_rule(rule, ctx)
        # Should NOT be not_measured anymore — the private matcher fired.
        self.assertFalse(cr.not_measured)
        self.assertEqual(len(cr.findings), 1)
        self.assertIn("ast_query", cr.findings[0].message)

    def test_cannot_override_oss_builtin(self):
        def _evil(ctx, cfg):
            return []

        for builtin in ("file_size", "path_glob", "manifest_field",
                        "regex_in_files", "command_in_makefile", "composite"):
            with self.assertRaises(ValueError):
                register_private_matcher(builtin, _evil)

    def test_unregister_private_matcher(self):
        def _noop(ctx, cfg):
            return []

        register_private_matcher("churn_signal", _noop)
        self.assertIn("churn_signal", OssMatchTypeRegistry)
        self.assertTrue(unregister_private_matcher("churn_signal"))
        self.assertNotIn("churn_signal", OssMatchTypeRegistry)
        # Idempotent — second unregister returns False, doesn't raise.
        self.assertFalse(unregister_private_matcher("churn_signal"))

    def test_unregister_refuses_oss_builtin(self):
        # Sanity: never let an unregister wipe a built-in.
        before = set(OssMatchTypeRegistry.keys())
        self.assertFalse(unregister_private_matcher("file_size"))
        self.assertEqual(set(OssMatchTypeRegistry.keys()), before)

    def test_unregistered_type_still_falls_through_to_not_measured(self):
        # No registration → unknown type → not_measured (existing behaviour).
        rule = LoadedRule(
            rule_id="x.unknown", pillar="flow", title="unknown",
            weight=1.0, severity="warn", explanation="",
            match={"type": "private_thing_nobody_registered"},
            fix_hint=None, insight_query=None, source_path=Path("/dev/null"),
        )
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"a.py": "x = 1"})
            cr = evaluate_rule(rule, ctx)
        self.assertTrue(cr.not_measured)


class TestInstalledRulesPackSmoke(unittest.TestCase):
    """Smoke tests against the installed ``agent_readiness_rules`` pkg.

    Q1 phase 4 dropped vendoring; the rules pack is now resolved
    through ``importlib.resources``. These tests assert that the
    install is wired correctly and that the Q1 generation of the pack
    (32 rules) is what we ship.
    """

    def test_default_rules_dir_resolves(self):
        rd = default_rules_dir()
        self.assertIsNotNone(
            rd,
            "agent-readiness-rules not installed; "
            "pip install agent-readiness-rules.",
        )
        self.assertTrue(rd.is_dir())

    def test_installed_pack_loads_q1_generation(self):
        rd = default_rules_dir()
        loaded = load_rules_from_dir(rd)
        # The Q1 generation ships 32 rules. Bumping this number is a
        # deliberate change in agent-readiness-rules and requires a
        # coordinated bump on this side.
        self.assertEqual(len(loaded), 32)

    def test_installed_pack_evaluates_on_self(self):
        rd = default_rules_dir()
        loaded = load_rules_from_dir(rd)
        ctx = RepoContext(root=Path(rd))
        results = evaluate_rules(loaded, ctx)
        self.assertEqual(len(results), len(loaded))


if __name__ == "__main__":
    unittest.main()
