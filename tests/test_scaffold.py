"""Tests for the ``agent-readiness scaffold`` command.

The scaffolder writes template files for rules that fire below
``score < 60``. Two behaviour contracts under test here:

1. The template-substitution step uses the same context-probe stack
   as rule-action templates, so ``{{INSTALL_COMMAND}}`` etc. in the
   bundled ``AGENTS.md`` template render to the *actual*
   language-specific command (e.g. ``sbt compile`` for Scala) rather
   than a literal placeholder.

2. ``agent_docs.canonical`` (the warn-level rule that fires when
   ``AGENTS.md`` is missing) maps to the bundled AGENTS.md template
   in ``_CHECK_TEMPLATES`` — pre-fix only ``agent_docs.present`` was
   listed, so the scaffolder could not seed AGENTS.md on a repo
   where the canonical-rule was the firing one.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_readiness.context import RepoContext
from agent_readiness.scaffold import _CHECK_TEMPLATES, _substitute


class TestScaffoldCheckTemplates(unittest.TestCase):
    def test_agent_docs_canonical_has_template_mapping(self):
        self.assertIn("agent_docs.canonical", _CHECK_TEMPLATES)
        self.assertEqual(
            _CHECK_TEMPLATES["agent_docs.canonical"],
            [("AGENTS.md", "AGENTS.md")],
        )

    def test_agent_docs_present_still_has_template_mapping(self):
        # Don't regress the existing scaffold entry — both rules must
        # remain mapped to the same template so the scaffolder seeds
        # AGENTS.md regardless of which rule fired first.
        self.assertIn("agent_docs.present", _CHECK_TEMPLATES)
        self.assertEqual(
            _CHECK_TEMPLATES["agent_docs.present"],
            [("AGENTS.md", "AGENTS.md")],
        )


class TestSubstitute(unittest.TestCase):
    def _ctx(self, files: dict[str, str]) -> tuple[TemporaryDirectory, RepoContext]:
        td = TemporaryDirectory()
        root = Path(td.name)
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return td, RepoContext(root=root)

    def test_scala_repo_resolves_sbt_commands(self):
        td, ctx = self._ctx({
            "build.sbt": "name := \"x\"\n",
            "src/main/scala/App.scala": "object App\n",
        })
        try:
            text = _substitute(
                "Lang: {{PRIMARY_LANGUAGE}}\n"
                "Install: {{INSTALL_COMMAND}}\n"
                "Test: {{TEST_COMMAND}}\n"
                "Lint: {{LINT_COMMAND}}\n",
                ctx,
            )
            self.assertIn("Lang: scala", text)
            self.assertIn("Install: sbt compile", text)
            self.assertIn("Test: sbt test", text)
            self.assertIn("Lint: sbt scalafmtCheckAll", text)
        finally:
            td.cleanup()

    def test_python_repo_resolves_pytest(self):
        td, ctx = self._ctx({
            "pyproject.toml": "[project]\nname = 'x'\n",
            "src/x.py": "x = 1\n",
        })
        try:
            text = _substitute(
                "Test: {{TEST_COMMAND}}\nLint: {{LINT_COMMAND}}\n",
                ctx,
            )
            self.assertIn("python -m pytest", text)
            self.assertIn("ruff check", text)
        finally:
            td.cleanup()

    def test_unclassifiable_repo_falls_back_to_human_readable_placeholder(self):
        """A repo with no manifest and no recognised file extensions
        should still render the template to readable English — the
        substitution falls back to ``your install command`` etc., not
        to a literal ``{{INSTALL_COMMAND}}`` token."""
        td, ctx = self._ctx({
            "README.md": "hi\n",
        })
        try:
            text = _substitute(
                "Lang: {{PRIMARY_LANGUAGE}}\nInstall: {{INSTALL_COMMAND}}\n",
                ctx,
            )
            self.assertIn("your project's primary language", text)
            self.assertIn("your install command", text)
            self.assertNotIn("{{", text)
        finally:
            td.cleanup()

    def test_repo_name_substitution_still_works(self):
        td, ctx = self._ctx({"a.py": "x\n"})
        try:
            text = _substitute("# {{REPO_NAME}}\n", ctx)
            # The repo root is a tempdir — name is non-empty random.
            self.assertNotIn("{{REPO_NAME}}", text)
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
