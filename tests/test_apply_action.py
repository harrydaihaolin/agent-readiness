"""Tests for ``agent_readiness.apply_action``.

Covers each of the 6 action kinds the v2 rules contract supports
plus the verify subprocess runner and the path-escape guard.

Layout mirrors the other engine tests: each scenario builds a minimal
``top_action`` dict in-test rather than going through ``compute_top_action``,
so a regression here points squarely at this module.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_readiness.apply_action import ApplyResult, apply_top_action


def _top_action(
    *,
    action: dict | None = None,
    verify: dict | None = None,
    check_id: str = "test.check",
) -> dict:
    """Minimal valid top_action shape (cf. scorer.compute_top_action)."""
    payload: dict = {
        "check_id": check_id,
        "pillar": "flow",
        "severity": "warn",
        "message": "test finding",
        "weight": 1.0,
        "rationale": "test",
    }
    if action is not None:
        payload["action"] = action
    if verify is not None:
        payload["verify"] = verify
    return payload


class TestSkipsAndErrors(unittest.TestCase):
    """No-action paths: None, missing action, unknown kind."""

    def test_none_top_action_skips_cleanly(self):
        result = apply_top_action(None, Path("."))
        self.assertFalse(result.applied)
        self.assertEqual(result.skipped_reason, "top_action is None")
        self.assertIsNone(result.error)

    def test_v1_rule_without_action_skips_with_reason(self):
        # rules_version=1 finding: only fix_hint, no structured action.
        top = _top_action()  # no `action` key
        result = apply_top_action(top, Path("."))
        self.assertFalse(result.applied)
        self.assertIn("no structured action", result.skipped_reason or "")
        self.assertIsNone(result.error)

    def test_unknown_kind_returns_error(self):
        top = _top_action(action={"kind": "telepathic_fix"})
        result = apply_top_action(top, Path("."))
        self.assertFalse(result.applied)
        self.assertIn("unknown action kind", result.error or "")

    def test_repo_path_must_be_directory(self):
        with TemporaryDirectory() as td:
            f = Path(td) / "not-a-dir.txt"
            f.write_text("")
            result = apply_top_action(
                _top_action(action={"kind": "create_file", "path": "x", "template": "y"}),
                f,
            )
            self.assertFalse(result.applied)
            self.assertIn("not a directory", result.error or "")


class TestCreateFile(unittest.TestCase):
    def test_creates_new_file(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "create_file",
                    "path": "AGENTS.md",
                    "template": "# Agents\n",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied, result)
            self.assertEqual(result.written, ["AGENTS.md"])
            self.assertEqual((repo / "AGENTS.md").read_text(), "# Agents\n")

    def test_creates_intermediate_directories(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "create_file",
                    "path": ".github/workflows/ci.yml",
                    "template": "name: CI\n",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied)
            self.assertTrue((repo / ".github" / "workflows" / "ci.yml").exists())

    def test_refuses_to_overwrite_existing(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "AGENTS.md").write_text("already here\n")
            top = _top_action(
                action={
                    "kind": "create_file",
                    "path": "AGENTS.md",
                    "template": "overwritten\n",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertFalse(result.applied)
            self.assertIn("already exists", result.error or "")
            # Original content preserved.
            self.assertEqual((repo / "AGENTS.md").read_text(), "already here\n")

    def test_path_escape_blocked(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "create_file",
                    "path": "../escape.txt",
                    "template": "evil\n",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertFalse(result.applied)
            self.assertIn("escapes repo", result.error or "")


class TestAppendToFile(unittest.TestCase):
    def test_appends_to_existing_file(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "Makefile").write_text("all:\n\techo hi\n")
            top = _top_action(
                action={
                    "kind": "append_to_file",
                    "path": "Makefile",
                    "template": "test:\n\tpytest\n",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied, result)
            self.assertEqual(result.written, ["Makefile"])
            content = (repo / "Makefile").read_text()
            self.assertIn("all:", content)
            self.assertIn("test:", content)

    def test_creates_when_absent(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "append_to_file",
                    "path": "TODO.md",
                    "template": "- write tests\n",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied)
            self.assertEqual((repo / "TODO.md").read_text(), "- write tests\n")

    def test_inserts_separator_when_missing_newline(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "README.md").write_text("# Title")  # no trailing newline
            top = _top_action(
                action={
                    "kind": "append_to_file",
                    "path": "README.md",
                    "template": "extra\n",
                },
            )
            apply_top_action(top, repo, run_verify=False)
            self.assertEqual((repo / "README.md").read_text(), "# Title\nextra\n")


class TestInsertAfter(unittest.TestCase):
    def test_inserts_after_pattern_match(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "Makefile").write_text(
                ".PHONY: all\nall:\n\techo hi\n"
            )
            top = _top_action(
                action={
                    "kind": "insert_after",
                    "path": "Makefile",
                    "after_pattern": r"^\.PHONY:.*$",
                    "template": "\nhelp:\n\t@echo 'help'\n",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied, result)
            content = (repo / "Makefile").read_text()
            phony_idx = content.index(".PHONY")
            help_idx = content.index("help:")
            all_idx = content.index("all:")
            self.assertLess(phony_idx, help_idx)
            self.assertLess(help_idx, all_idx)

    def test_missing_file_errors(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "insert_after",
                    "path": "Missing",
                    "after_pattern": "^x$",
                    "template": "y\n",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertFalse(result.applied)
            self.assertIn("not found", result.error or "")

    def test_pattern_not_found_errors(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "f.txt").write_text("nothing matches here\n")
            top = _top_action(
                action={
                    "kind": "insert_after",
                    "path": "f.txt",
                    "after_pattern": r"^missing$",
                    "template": "x\n",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertFalse(result.applied)
            self.assertIn("not found", result.error or "")


class TestEditGitignore(unittest.TestCase):
    def test_appends_missing_entries(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".gitignore").write_text("__pycache__/\n")
            top = _top_action(
                action={
                    "kind": "edit_gitignore",
                    "entries": [".venv/", "*.pyc", "__pycache__/"],  # one duplicate
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied)
            self.assertEqual(result.written, [".gitignore"])
            content = (repo / ".gitignore").read_text()
            self.assertEqual(content.count("__pycache__/"), 1)
            self.assertIn(".venv/", content)
            self.assertIn("*.pyc", content)

    def test_creates_gitignore_when_absent(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "edit_gitignore",
                    "entries": [".env"],
                },
            )
            apply_top_action(top, repo, run_verify=False)
            self.assertEqual((repo / ".gitignore").read_text(), ".env\n")

    def test_idempotent_when_all_present(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".gitignore").write_text(".env\n")
            top = _top_action(
                action={
                    "kind": "edit_gitignore",
                    "entries": [".env"],
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied)
            self.assertEqual(result.written, [])  # no-op


class TestModifyManifestField(unittest.TestCase):
    def test_json_sets_dotted_field(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "package.json").write_text(json.dumps({"name": "x"}))
            top = _top_action(
                action={
                    "kind": "modify_manifest_field",
                    "manifest": "package.json",
                    "field_path": "scripts.test",
                    "value": "vitest",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied, result)
            data = json.loads((repo / "package.json").read_text())
            self.assertEqual(data["scripts"]["test"], "vitest")

    def test_toml_appends_table_when_missing(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "pyproject.toml").write_text(
                "[project]\nname = \"x\"\n"
            )
            top = _top_action(
                action={
                    "kind": "modify_manifest_field",
                    "manifest": "pyproject.toml",
                    "field_path": "tool.ruff.line-length",
                    "value": "100",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied, result)
            content = (repo / "pyproject.toml").read_text()
            self.assertIn("[tool.ruff]", content)
            self.assertIn("line-length", content)

    def test_toml_idempotent_when_already_set(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "pyproject.toml").write_text(
                "[project]\nname = \"x\"\n[tool.ruff]\nline-length = 100\n"
            )
            top = _top_action(
                action={
                    "kind": "modify_manifest_field",
                    "manifest": "pyproject.toml",
                    "field_path": "tool.ruff.line-length",
                    "value": "120",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied)
            self.assertEqual(result.written, [])  # idempotent

    def test_unsupported_manifest_extension_errors(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "config.ini").write_text("[section]\nkey = value\n")
            top = _top_action(
                action={
                    "kind": "modify_manifest_field",
                    "manifest": "config.ini",
                    "field_path": "section.key",
                    "value": "other",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertFalse(result.applied)
            self.assertIn("unsupported manifest type", result.error or "")


class TestRunCommand(unittest.TestCase):
    def test_success_returns_applied_with_empty_written(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "run_command",
                    "command": "touch sentinel.txt",
                    "description": "test sentinel",
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied, result)
            self.assertEqual(result.written, [])  # see docstring
            self.assertTrue((repo / "sentinel.txt").exists())

    def test_failure_surfaces_as_error(self):
        with TemporaryDirectory() as td:
            top = _top_action(
                action={
                    "kind": "run_command",
                    "command": "false",
                    "description": "always fails",
                },
            )
            result = apply_top_action(top, Path(td), run_verify=False)
            self.assertFalse(result.applied)
            self.assertIn("run_command failed", result.error or "")


class TestVerifyRunner(unittest.TestCase):
    def test_verify_success_marks_verified_true(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "create_file",
                    "path": "AGENTS.md",
                    "template": "ok\n",
                },
                verify={
                    "command": "test -f AGENTS.md",
                    "timeout_seconds": 5,
                },
            )
            result = apply_top_action(top, repo)
            self.assertTrue(result.applied, result)
            self.assertTrue(result.verified)
            self.assertEqual(result.verify["exit_code"], 0)

    def test_verify_failure_marks_verified_false(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "create_file",
                    "path": "AGENTS.md",
                    "template": "ok\n",
                },
                verify={
                    "command": "test -f NOPE.md",
                    "timeout_seconds": 5,
                },
            )
            result = apply_top_action(top, repo)
            self.assertTrue(result.applied)
            self.assertFalse(result.verified)
            self.assertEqual(result.verify["exit_code"], 1)

    def test_run_verify_false_skips_command(self):
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "create_file",
                    "path": "AGENTS.md",
                    "template": "ok\n",
                },
                verify={
                    "command": "exit 1",  # would fail if run
                    "timeout_seconds": 5,
                },
            )
            result = apply_top_action(top, repo, run_verify=False)
            self.assertTrue(result.applied)
            self.assertIsNone(result.verified)
            self.assertIsNone(result.verify)

    def test_verify_block_without_command_keeps_verified_none(self):
        # No verify block at all => verified stays None.
        with TemporaryDirectory() as td:
            repo = Path(td)
            top = _top_action(
                action={
                    "kind": "create_file",
                    "path": "AGENTS.md",
                    "template": "ok\n",
                },
            )
            result = apply_top_action(top, repo)
            self.assertTrue(result.applied)
            self.assertIsNone(result.verified)


class TestApplyResultSerialization(unittest.TestCase):
    def test_to_dict_strips_none_and_empty(self):
        r = ApplyResult(applied=True, written=[])
        d = r.to_dict()
        self.assertEqual(d, {"applied": True})

    def test_to_dict_keeps_populated_fields(self):
        r = ApplyResult(
            applied=True,
            written=["a", "b"],
            verified=True,
            verify={"command": "true", "exit_code": 0},
        )
        d = r.to_dict()
        self.assertEqual(d["applied"], True)
        self.assertEqual(d["written"], ["a", "b"])
        self.assertEqual(d["verified"], True)
        self.assertEqual(d["verify"]["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
