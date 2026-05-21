"""Tests for src/agent_readiness/rules_eval/private_matchers/.

Covers the OSS-shipped private matchers used by YAML rules in
``agent-readiness-rules`` for analyses that can't be expressed with
the six declarative OSS match types. Each matcher gets a focused
no-fire / fire pair plus its mode-dispatch behaviour.

Coverage target is *behavioural correctness*, not exhaustive parity
with the legacy ``@register`` checks — those tests live alongside
the original modules and continue to pass through Phase 3.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval import OssMatchTypeRegistry

# Trigger registration via the package import side effect.
from agent_readiness.rules_eval import private_matchers  # noqa: F401


def _make_ctx(tmpdir: Path, files: dict[str, str]) -> RepoContext:
    for rel, content in files.items():
        p = tmpdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return RepoContext(root=tmpdir)


def _git_init(tmpdir: Path, *, commits: int = 0) -> None:
    """Initialise a git repo in tmpdir with N commits."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True, env=env)
    subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=tmpdir,
                   capture_output=True, check=False, env=env)
    for i in range(commits):
        marker = tmpdir / f"_commit_{i}.txt"
        marker.write_text(str(i))
        subprocess.run(["git", "add", "-A"], cwd=tmpdir, check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", f"c{i}"], cwd=tmpdir,
                       check=True, env=env)


class TestRegistration(unittest.TestCase):
    """Every OSS private matcher must be registered when the package
    is imported. This guards against silent dispatch breakage."""

    EXPECTED = {
        "git_log_query", "ast_complexity", "regex_secret_scan",
        "gh_cli_query", "naming_search", "tree_aggregate",
        "cross_file_consistency", "prompt_scan", "setup_command_count",
        "manifest_introspection", "gitignore_coverage",
    }

    def test_all_oss_private_matchers_registered(self):
        registered = set(OssMatchTypeRegistry.keys())
        missing = self.EXPECTED - registered
        self.assertFalse(missing, f"missing private matchers: {missing}")


class TestGitLogQuery(unittest.TestCase):
    def test_commit_count_neutral_on_shallow(self):
        from agent_readiness.rules_eval.private_matchers.git_log_query import match_git_log_query
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {".git/shallow": "deadbeef\n", "a.py": "x"})
            findings = match_git_log_query(ctx, {"mode": "commit_count", "min_commits": 5})
            self.assertEqual(findings, [])

    def test_commit_count_fires_when_too_few(self):
        from agent_readiness.rules_eval.private_matchers.git_log_query import match_git_log_query
        with TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "a.py").write_text("x\n")
            _git_init(tmp, commits=1)
            ctx = RepoContext(root=tmp)
            findings = match_git_log_query(ctx, {"mode": "commit_count", "min_commits": 5})
            self.assertEqual(len(findings), 1)
            self.assertIn("min_commits=5", findings[0][2])

    def test_commit_count_clean_when_enough(self):
        from agent_readiness.rules_eval.private_matchers.git_log_query import match_git_log_query
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _git_init(tmp, commits=6)
            ctx = RepoContext(root=tmp)
            findings = match_git_log_query(ctx, {"mode": "commit_count", "min_commits": 5})
            self.assertEqual(findings, [])

    def test_unknown_mode_returns_no_findings(self):
        from agent_readiness.rules_eval.private_matchers.git_log_query import match_git_log_query
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"a.py": "x"})
            self.assertEqual(match_git_log_query(ctx, {"mode": "garbage"}), [])


class TestAstComplexity(unittest.TestCase):
    def test_no_findings_when_lizard_missing(self):
        # We don't assert lizard is missing — just that the matcher
        # never raises on a clean dir, regardless of lizard install state.
        from agent_readiness.rules_eval.private_matchers.ast_complexity import match_ast_complexity
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"a.py": "x = 1\n"})
            findings = match_ast_complexity(ctx, {"max_cc": 15, "languages": ["python"]})
            self.assertEqual(findings, [])  # trivial file → no high-CC functions

    def test_fires_on_high_cc_function(self):
        try:
            import lizard  # noqa: F401
        except ImportError:
            self.skipTest("lizard not installed; skipping fire test")
        from agent_readiness.rules_eval.private_matchers.ast_complexity import match_ast_complexity
        # Function with many `if` branches → high cyclomatic complexity.
        body = "\n".join(f"    if x == {i}: return {i}" for i in range(20))
        src = f"def big(x):\n{body}\n    return None\n"
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"big.py": src})
            findings = match_ast_complexity(ctx, {"max_cc": 5, "languages": ["python"], "top_n": 3})
            self.assertTrue(findings)
            self.assertIn("'big'", findings[0][2])


class TestRegexSecretScan(unittest.TestCase):
    PATTERNS = [
        {"name": "aws_access_key_id", "regex": r"\bAKIA[0-9A-Z]{16}\b"},
    ]

    def test_no_findings_clean(self):
        from agent_readiness.rules_eval.private_matchers.regex_secret_scan import match_regex_secret_scan
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"a.py": "x = 'hello'\n"})
            findings = match_regex_secret_scan(ctx, {"patterns": self.PATTERNS})
            self.assertEqual(findings, [])

    def test_fires_on_aws_key(self):
        from agent_readiness.rules_eval.private_matchers.regex_secret_scan import match_regex_secret_scan
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"config.py": 'KEY = "AKIAIOSFODNN7EXAMPLE"\n'})
            findings = match_regex_secret_scan(ctx, {"patterns": self.PATTERNS})
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0][0], "config.py")
            self.assertIn("aws_access_key_id", findings[0][2])

    def test_excludes_path_segments(self):
        from agent_readiness.rules_eval.private_matchers.regex_secret_scan import match_regex_secret_scan
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"tests/fixtures/a.py": 'KEY = "AKIAIOSFODNN7EXAMPLE"\n'})
            findings = match_regex_secret_scan(
                ctx, {"patterns": self.PATTERNS, "exclude_path_segments": ["test", "fixture"]}
            )
            self.assertEqual(findings, [])


class TestNamingSearch(unittest.TestCase):
    def test_no_findings_on_specific_names(self):
        from agent_readiness.rules_eval.private_matchers.naming_search import match_naming_search
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"src/auth.py": "x", "src/payment_gateway.py": "x"})
            findings = match_naming_search(
                ctx, {"ambiguous_stems": ["utils", "helpers"], "max_depth": 2}
            )
            self.assertEqual(findings, [])

    def test_fires_on_utils(self):
        from agent_readiness.rules_eval.private_matchers.naming_search import match_naming_search
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"utils.py": "x", "src/helpers.py": "x"})
            findings = match_naming_search(
                ctx, {"ambiguous_stems": ["utils", "helpers"], "max_depth": 2}
            )
            self.assertEqual(len(findings), 2)

    def test_excludes_conventional_parent_dirs(self):
        from agent_readiness.rules_eval.private_matchers.naming_search import match_naming_search
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"tests/utils.py": "x", "scripts/helpers.sh": "x"})
            findings = match_naming_search(
                ctx,
                {"ambiguous_stems": ["utils", "helpers"], "max_depth": 2,
                 "exclude_parent_dirs": ["tests", "scripts"]},
            )
            self.assertEqual(findings, [])


class TestTreeAggregate(unittest.TestCase):
    def test_top_level_count_fires_when_too_many(self):
        from agent_readiness.rules_eval.private_matchers.tree_aggregate import match_tree_aggregate
        with TemporaryDirectory() as td:
            files = {f"f{i}.py": "x" for i in range(25)}
            ctx = _make_ctx(Path(td), files)
            findings = match_tree_aggregate(ctx, {"mode": "top_level_count", "warn_above": 20})
            self.assertEqual(len(findings), 1)
            self.assertIn("25", findings[0][2])

    def test_top_level_count_clean_under_threshold(self):
        from agent_readiness.rules_eval.private_matchers.tree_aggregate import match_tree_aggregate
        with TemporaryDirectory() as td:
            files = {f"f{i}.py": "x" for i in range(5)}
            ctx = _make_ctx(Path(td), files)
            findings = match_tree_aggregate(ctx, {"mode": "top_level_count", "warn_above": 20})
            self.assertEqual(findings, [])

    def test_top_level_count_excludes_meta_stems(self):
        from agent_readiness.rules_eval.private_matchers.tree_aggregate import match_tree_aggregate
        with TemporaryDirectory() as td:
            files = {"README.md": "x", "LICENSE": "x", "Makefile": "x"}
            ctx = _make_ctx(Path(td), files)
            findings = match_tree_aggregate(
                ctx,
                {"mode": "top_level_count", "warn_above": 0,
                 "exclude_stems": ["readme", "license", "makefile"]},
            )
            self.assertEqual(findings, [])

    def test_orientation_tokens_clean_for_small_repo(self):
        from agent_readiness.rules_eval.private_matchers.tree_aggregate import match_tree_aggregate
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"README.md": "small\n"})
            findings = match_tree_aggregate(
                ctx, {"mode": "orientation_tokens", "warn_tokens": 24000}
            )
            self.assertEqual(findings, [])


class TestCrossFileConsistency(unittest.TestCase):
    def test_env_parity_no_refs_no_findings(self):
        from agent_readiness.rules_eval.private_matchers.cross_file_consistency import match_cross_file_consistency
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"src/a.py": "x = 1\n"})
            findings = match_cross_file_consistency(
                ctx,
                {"mode": "env_parity", "env_patterns": [r"os\.environ"],
                 "source_globs": ["src/*.py"], "require_one_of": [".env.example"]},
            )
            self.assertEqual(findings, [])

    def test_env_parity_fires_when_refs_but_no_example(self):
        from agent_readiness.rules_eval.private_matchers.cross_file_consistency import match_cross_file_consistency
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"src/a.py": "import os\nx = os.environ['DB']\n"})
            findings = match_cross_file_consistency(
                ctx,
                {"mode": "env_parity", "env_patterns": [r"os\.environ"],
                 "source_globs": ["src/*.py"], "require_one_of": [".env.example"]},
            )
            self.assertEqual(len(findings), 1)

    def test_env_parity_clean_when_example_present(self):
        from agent_readiness.rules_eval.private_matchers.cross_file_consistency import match_cross_file_consistency
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {
                "src/a.py": "import os\nx = os.environ['DB']\n",
                ".env.example": "DB=\n",
            })
            findings = match_cross_file_consistency(
                ctx,
                {"mode": "env_parity", "env_patterns": [r"os\.environ"],
                 "source_globs": ["src/*.py"], "require_one_of": [".env.example"]},
            )
            self.assertEqual(findings, [])

    def test_readme_repo_match_pytest_mention_without_config(self):
        from agent_readiness.rules_eval.private_matchers.cross_file_consistency import match_cross_file_consistency
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"README.md": "Run pytest to test.\n"})
            findings = match_cross_file_consistency(
                ctx, {"mode": "readme_repo_match", "checks": ["pytest_mention_requires_config"]}
            )
            self.assertEqual(len(findings), 1)
            self.assertIn("pytest", findings[0][2])

    def test_readme_repo_match_placeholder_agent_doc(self):
        from agent_readiness.rules_eval.private_matchers.cross_file_consistency import match_cross_file_consistency
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"AGENTS.md": "TODO\n"})
            findings = match_cross_file_consistency(
                ctx, {"mode": "readme_repo_match", "checks": ["agent_doc_not_placeholder"]}
            )
            self.assertEqual(len(findings), 1)
            self.assertIn("placeholder", findings[0][2])


class TestPromptScan(unittest.TestCase):
    def test_readme_run_instructions_no_readme(self):
        from agent_readiness.rules_eval.private_matchers.prompt_scan import match_prompt_scan
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"src/a.py": "x"})
            findings = match_prompt_scan(
                ctx, {"mode": "readme_run_instructions", "signals": ["install", "run", "test"]}
            )
            self.assertEqual(len(findings), 1)
            self.assertIn("No README", findings[0][2])

    def test_readme_run_instructions_complete(self):
        from agent_readiness.rules_eval.private_matchers.prompt_scan import match_prompt_scan
        with TemporaryDirectory() as td:
            text = "## Install\n```\npip install x\n```\n## Run\n```\nx\n```\n## Test\n```\npytest\n```"
            ctx = _make_ctx(Path(td), {"README.md": text})
            findings = match_prompt_scan(
                ctx,
                {"mode": "readme_run_instructions",
                 "signals": ["install", "run", "test"], "require_fenced_code": True},
            )
            self.assertEqual(findings, [])

    def test_readme_run_instructions_missing_fenced_code(self):
        from agent_readiness.rules_eval.private_matchers.prompt_scan import match_prompt_scan
        with TemporaryDirectory() as td:
            text = "Install with pip. Run the CLI. Test with pytest."
            ctx = _make_ctx(Path(td), {"README.md": text})
            findings = match_prompt_scan(
                ctx,
                {"mode": "readme_run_instructions",
                 "signals": ["install", "run", "test"], "require_fenced_code": True},
            )
            self.assertTrue(any("fenced code" in f[2] for f in findings))

    def test_headless_setup_fires_on_gui_phrase(self):
        from agent_readiness.rules_eval.private_matchers.prompt_scan import match_prompt_scan
        with TemporaryDirectory() as td:
            text = "## Install\nClick here in the dashboard to start.\n"
            ctx = _make_ctx(Path(td), {"README.md": text})
            findings = match_prompt_scan(
                ctx,
                {"mode": "headless_setup", "gui_phrases": ["in the dashboard"]},
            )
            self.assertEqual(len(findings), 1)
            self.assertIn("GUI step", findings[0][2])


class TestSetupCommandCount(unittest.TestCase):
    def test_no_readme_no_findings(self):
        from agent_readiness.rules_eval.private_matchers.setup_command_count import match_setup_command_count
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"a.py": "x"})
            self.assertEqual(match_setup_command_count(ctx, {"max_commands": 5}), [])

    def test_fires_on_too_many_commands(self):
        from agent_readiness.rules_eval.private_matchers.setup_command_count import match_setup_command_count
        with TemporaryDirectory() as td:
            text = (
                "## Install\n```bash\n"
                "step1\nstep2\nstep3\nstep4\nstep5\nstep6\nstep7\n"
                "```\n## Other\n"
            )
            ctx = _make_ctx(Path(td), {"README.md": text})
            findings = match_setup_command_count(ctx, {"max_commands": 5})
            self.assertEqual(len(findings), 1)
            self.assertIn("7 distinct commands", findings[0][2])

    def test_clean_under_threshold(self):
        from agent_readiness.rules_eval.private_matchers.setup_command_count import match_setup_command_count
        with TemporaryDirectory() as td:
            text = "## Install\n```bash\nmake install\n```\n"
            ctx = _make_ctx(Path(td), {"README.md": text})
            self.assertEqual(match_setup_command_count(ctx, {"max_commands": 5}), [])


class TestManifestIntrospection(unittest.TestCase):
    def test_clean_when_pyproject_present(self):
        from agent_readiness.rules_eval.private_matchers.manifest_introspection import match_manifest_introspection
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"pyproject.toml": "[project]\nname='x'\n"})
            self.assertEqual(match_manifest_introspection(ctx, {"mode": "any_manifest_present"}), [])

    def test_clean_when_monorepo_manifest_at_depth_two(self):
        # The matcher (faithful to the legacy @register check) looks
        # for monorepo manifests where len(path.parts) == 2 — i.e.
        # `<subdir>/package.json`, not deeper layouts. The typical
        # `packages/web/package.json` (3-part) layout is a follow-up.
        from agent_readiness.rules_eval.private_matchers.manifest_introspection import match_manifest_introspection
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"web/package.json": "{}"})
            findings = match_manifest_introspection(
                ctx, {"mode": "any_manifest_present", "monorepo_depth": 2}
            )
            self.assertEqual(findings, [])

    def test_fires_when_no_manifest(self):
        from agent_readiness.rules_eval.private_matchers.manifest_introspection import match_manifest_introspection
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"src/code.py": "x"})
            findings = match_manifest_introspection(ctx, {"mode": "any_manifest_present"})
            self.assertEqual(len(findings), 1)
            self.assertIn("No project manifest", findings[0][2])

    def test_clean_on_scala_sbt_repo(self):
        """``build.sbt`` is a first-class manifest. A pure-Scala repo
        with no other manifest should not fire the "no manifest" finding.
        Pre-fix this would fire because ``_ROOT_MANIFESTS`` listed
        ``pom.xml`` / ``build.gradle*`` but not ``build.sbt``.
        """
        from agent_readiness.rules_eval.private_matchers.manifest_introspection import match_manifest_introspection
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"build.sbt": "name := \"x\"\n"})
            self.assertEqual(
                match_manifest_introspection(ctx, {"mode": "any_manifest_present"}),
                [],
            )

    def test_clean_on_clojure_deps_repo(self):
        """``deps.edn`` (modern Clojure CLI) is a first-class manifest."""
        from agent_readiness.rules_eval.private_matchers.manifest_introspection import match_manifest_introspection
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"deps.edn": "{:deps {}}"})
            self.assertEqual(
                match_manifest_introspection(ctx, {"mode": "any_manifest_present"}),
                [],
            )

    def test_clean_on_julia_project_repo(self):
        """``Project.toml`` is the canonical Julia manifest."""
        from agent_readiness.rules_eval.private_matchers.manifest_introspection import match_manifest_introspection
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"Project.toml": "name = \"X\"\n"})
            self.assertEqual(
                match_manifest_introspection(ctx, {"mode": "any_manifest_present"}),
                [],
            )


class TestGitignoreCoverage(unittest.TestCase):
    def test_fires_when_no_gitignore(self):
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import match_gitignore_coverage
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"a.py": "x"})
            findings = match_gitignore_coverage(ctx, {"min_groups_covered": 2})
            self.assertEqual(len(findings), 1)
            self.assertIn("No .gitignore", findings[0][2])

    def test_fires_when_below_min_coverage(self):
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import match_gitignore_coverage
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {".gitignore": "# minimal\n*.log\n"})
            findings = match_gitignore_coverage(
                ctx,
                {"groups": ["python_pycache", "node_modules", "logs"], "min_groups_covered": 2},
            )
            self.assertEqual(len(findings), 1)
            self.assertIn("missing", findings[0][2])

    def test_clean_when_above_min_coverage(self):
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import match_gitignore_coverage
        with TemporaryDirectory() as td:
            text = "__pycache__\nnode_modules\n.env\n"
            ctx = _make_ctx(Path(td), {".gitignore": text})
            findings = match_gitignore_coverage(
                ctx,
                {"groups": ["python_pycache", "node_modules", "dotenv"], "min_groups_covered": 2},
            )
            self.assertEqual(findings, [])

    def test_unknown_group_counts_as_missing(self):
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import match_gitignore_coverage
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {".gitignore": "__pycache__\n"})
            findings = match_gitignore_coverage(
                ctx,
                {"groups": ["python_pycache", "typo_name"], "min_groups_covered": 2},
            )
            self.assertEqual(len(findings), 1)
            self.assertIn("typo_name", findings[0][2])

    def test_language_aware_passes_on_scala_repo(self):
        """A Scala repo whose .gitignore covers JVM + universal groups
        but not python/node/go ones should pass under language_aware mode.

        This is the literal repro for the score-chasing complaint:
        before language_aware, the matcher required 7/12 groups and a
        bare-Scala repo could only cover ~5, so it fired and pulled the
        safety pillar below 100. The post-fix expectation is that the
        rule passes with no findings because every Scala-relevant group
        is covered.
        """
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import match_gitignore_coverage
        scala_gitignore = (
            "*.class\n"
            "target/\n"
            ".idea/\n"
            ".vscode/\n"
            ".DS_Store\n"
            ".env\n"
            ".env.*\n"
            "*.log\n"
        )
        with TemporaryDirectory() as td:
            ctx = _make_ctx(
                Path(td),
                {
                    "build.sbt": "name := \"x\"\n",
                    ".gitignore": scala_gitignore,
                    "src/main/scala/App.scala": "object App\n",
                },
            )
            findings = match_gitignore_coverage(
                ctx,
                {
                    "language_aware": True,
                    "groups": [
                        "python_pycache", "node_modules", "dotenv", "dist_build",
                        "go_vendor", "rust_target", "jvm_class", "ide_junk",
                        "python_egg_info", "coverage", "terraform", "logs",
                    ],
                    "min_groups_covered": 7,
                },
            )
            self.assertEqual(findings, [])

    def test_language_aware_fires_on_scala_repo_missing_secrets_group(self):
        """Language-aware mode still enforces the universal groups
        (dotenv / ide_junk / logs). A Scala repo that ignores `target/`
        and `*.class` but forgets `.env` should still fire — the dotenv
        risk is language-agnostic.
        """
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import match_gitignore_coverage
        scala_gitignore = (
            "*.class\n"
            "target/\n"
            ".idea/\n"
            "*.log\n"
            # no .env line on purpose.
        )
        with TemporaryDirectory() as td:
            ctx = _make_ctx(
                Path(td),
                {
                    "build.sbt": "name := \"x\"\n",
                    ".gitignore": scala_gitignore,
                    "src/main/scala/App.scala": "object App\n",
                },
            )
            findings = match_gitignore_coverage(
                ctx,
                {
                    "language_aware": True,
                    "groups": [
                        "python_pycache", "node_modules", "dotenv", "dist_build",
                        "go_vendor", "rust_target", "jvm_class", "ide_junk",
                        "python_egg_info", "coverage", "terraform", "logs",
                    ],
                    "min_groups_covered": 7,
                },
            )
            self.assertEqual(len(findings), 1)
            self.assertIn("dotenv", findings[0][2])

    def test_language_aware_passes_on_python_node_monorepo(self):
        """Multi-language repos (Python + Node) require the *union*
        of language-specific groups. Both `__pycache__` AND
        `node_modules` must be covered."""
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import match_gitignore_coverage
        gi = "__pycache__\nnode_modules\n.env\n.idea/\n*.log\ndist/\n"
        with TemporaryDirectory() as td:
            ctx = _make_ctx(
                Path(td),
                {
                    "pyproject.toml": "[project]\nname='x'\n",
                    ".gitignore": gi,
                    "src/a.py": "x\n",
                    "web/index.js": "x\n",
                },
            )
            findings = match_gitignore_coverage(
                ctx,
                {
                    "language_aware": True,
                    "groups": [
                        "python_pycache", "node_modules", "dotenv", "dist_build",
                        "ide_junk", "logs",
                    ],
                    "min_groups_covered": 6,
                },
            )
            self.assertEqual(findings, [])

    def test_language_aware_python_allows_one_miss_in_lang_groups(self):
        """Regression test for the v2.4.0 -> v2.4.3 calibration finding:
        v2.4.0 made language_aware mode strict ("every required group
        must be present"), which silently tightened the bar for
        ecosystems with >=3 language-specific groups. Python had 4
        language groups + 3 universals = 7 in scope; a previously
        passing repo missing only `coverage` newly fired. The 2026-05-21
        calibration cycle measured this as a +4.1pp regression in the
        full v3 cohort. The fix allows one language-group miss when the
        detected ecosystem has >=3 language-specific groups in scope.
        Universals stay non-negotiable."""
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import (
            match_gitignore_coverage,
        )
        # Python repo missing only the `coverage` group — three universals
        # present (`.env`, `.idea/`, `*.log`), plus `__pycache__`,
        # `.egg-info/`, `dist/` — but no `htmlcov/` / `.pytest_cache/` /
        # `coverage/` patterns.
        gi = (
            ".env\n"
            ".idea/\n"
            "*.log\n"
            "__pycache__/\n"
            "*.egg-info/\n"
            "dist/\n"
            # NB: no coverage/ pattern
        )
        with TemporaryDirectory() as td:
            ctx = _make_ctx(
                Path(td),
                {
                    "pyproject.toml": "[project]\nname='x'\n",
                    ".gitignore": gi,
                    "src/a.py": "x\n",
                },
            )
            findings = match_gitignore_coverage(
                ctx,
                {
                    "language_aware": True,
                    "groups": [
                        "python_pycache", "node_modules", "dotenv", "dist_build",
                        "go_vendor", "rust_target", "jvm_class", "ide_junk",
                        "python_egg_info", "coverage", "terraform", "logs",
                        "swift_build",
                    ],
                    "min_groups_covered": 7,
                },
            )
            # Was firing in v2.4.0 (strict). After the fix: one language
            # miss in a 4-lang-group ecosystem is allowed.
            self.assertEqual(findings, [], "Python repo missing only `coverage` should pass under v2.4.3+ semantics")

    def test_language_aware_python_still_fires_on_universal_miss(self):
        """Universals (dotenv, ide_junk, logs) must stay non-negotiable
        even with the miss-budget tolerance. A Python repo that covers
        all 4 language groups but lacks `.env` should still fire."""
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import (
            match_gitignore_coverage,
        )
        # Missing .env entirely (no dotenv group), but has everything else.
        gi = (
            ".idea/\n"
            "*.log\n"
            "__pycache__/\n"
            "*.egg-info/\n"
            "dist/\n"
            "htmlcov/\n"
        )
        with TemporaryDirectory() as td:
            ctx = _make_ctx(
                Path(td),
                {
                    "pyproject.toml": "[project]\nname='x'\n",
                    ".gitignore": gi,
                    "src/a.py": "x\n",
                },
            )
            findings = match_gitignore_coverage(
                ctx,
                {
                    "language_aware": True,
                    "groups": [
                        "python_pycache", "node_modules", "dotenv", "dist_build",
                        "go_vendor", "rust_target", "jvm_class", "ide_junk",
                        "python_egg_info", "coverage", "terraform", "logs",
                        "swift_build",
                    ],
                    "min_groups_covered": 7,
                },
            )
            self.assertEqual(len(findings), 1, "Missing universal group must always fire")
            self.assertIn("dotenv", findings[0][2])

    def test_language_aware_rust_still_strict_on_single_lang_group(self):
        """Rust has only one language-specific group in scope
        (`rust_target`). The miss-budget tolerance kicks in only when
        lang_count >= 3; with lang_count=1 the matcher stays strict so
        the language signal isn't silently waived."""
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import (
            match_gitignore_coverage,
        )
        # Three universals present, but `target/` missing.
        gi = ".env\n.idea/\n*.log\n"
        with TemporaryDirectory() as td:
            ctx = _make_ctx(
                Path(td),
                {
                    "Cargo.toml": '[package]\nname = "x"\nversion = "0.1.0"\n',
                    ".gitignore": gi,
                    "src/main.rs": "fn main() {}\n",
                },
            )
            findings = match_gitignore_coverage(
                ctx,
                {
                    "language_aware": True,
                    "groups": [
                        "python_pycache", "node_modules", "dotenv", "dist_build",
                        "go_vendor", "rust_target", "jvm_class", "ide_junk",
                        "python_egg_info", "coverage", "terraform", "logs",
                        "swift_build",
                    ],
                    "min_groups_covered": 7,
                },
            )
            self.assertEqual(len(findings), 1, "Rust repo missing rust_target should still fire")
            self.assertIn("rust_target", findings[0][2])

    def test_language_aware_falls_back_when_no_language_detected(self):
        """If the engine can't classify the repo (no manifest, no
        recognised file extensions), the matcher falls back to the
        non-language-aware behaviour — every requested group is
        required. This is the safer default; we'd rather over-fire on
        unclassifiable repos than silently under-fire on real misses."""
        from agent_readiness.rules_eval.private_matchers.gitignore_coverage import match_gitignore_coverage
        with TemporaryDirectory() as td:
            ctx = _make_ctx(
                Path(td),
                {
                    "README.md": "hi\n",
                    ".gitignore": ".env\n*.log\n.idea/\n",
                },
            )
            findings = match_gitignore_coverage(
                ctx,
                {
                    "language_aware": True,
                    "groups": ["python_pycache", "node_modules", "dotenv", "ide_junk", "logs"],
                    "min_groups_covered": 5,
                },
            )
            # Only 3/5 covered; missing python_pycache + node_modules.
            self.assertEqual(len(findings), 1)


class TestGhCliQuery(unittest.TestCase):
    """gh_cli_query is heavily networked; tests focus on graceful
    no-op behaviour when prerequisites aren't met."""

    def test_no_gh_cli_returns_no_findings(self):
        from agent_readiness.rules_eval.private_matchers.gh_cli_query import match_gh_cli_query
        with TemporaryDirectory() as td:
            # No git init → ctx.is_git_repo is False → matcher returns no findings.
            ctx = _make_ctx(Path(td), {"a.py": "x"})
            findings = match_gh_cli_query(
                ctx, {"api_path": "repos/{owner}/{repo}/rulesets", "fire_when": "empty"}
            )
            self.assertEqual(findings, [])

    def test_missing_api_path_returns_no_findings(self):
        from agent_readiness.rules_eval.private_matchers.gh_cli_query import match_gh_cli_query
        with TemporaryDirectory() as td:
            ctx = _make_ctx(Path(td), {"a.py": "x"})
            findings = match_gh_cli_query(ctx, {"fire_when": "empty"})
            self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
