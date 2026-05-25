"""Tests for the regex_in_files builtin matcher.

Mirrors tests/test_matchers.py in agent-readiness-insights so OSS and
proprietary matchers stay parity (per CLAUDE.md cross-repo invariant).
"""
from __future__ import annotations

from pathlib import Path

from agent_readiness.context import RepoContext
from agent_readiness.rules_eval.matchers._builtins import match_regex_in_files


def test_match_fires_when_pattern_matches(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello world\n")
    ctx = RepoContext(root=tmp_path)
    findings = match_regex_in_files(
        ctx,
        {"pattern": "hello", "file_globs": ["*.txt"], "fire_when": "match"},
    )
    assert findings, "expected a match-mode finding for present pattern"
    assert findings[0][0] == "a.txt"


def test_match_no_fire_when_pattern_absent(tmp_path: Path):
    (tmp_path / "a.txt").write_text("goodbye world\n")
    ctx = RepoContext(root=tmp_path)
    findings = match_regex_in_files(
        ctx,
        {"pattern": "hello", "file_globs": ["*.txt"], "fire_when": "match"},
    )
    assert findings == []


def test_no_match_fires_when_pattern_absent(tmp_path: Path):
    (tmp_path / "a.txt").write_text("goodbye world\n")
    ctx = RepoContext(root=tmp_path)
    findings = match_regex_in_files(
        ctx,
        {"pattern": "hello", "file_globs": ["*.txt"], "fire_when": "no_match"},
    )
    assert findings, "expected a no_match-mode finding when pattern is absent"


def test_no_match_no_fire_when_pattern_present(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello world\n")
    ctx = RepoContext(root=tmp_path)
    findings = match_regex_in_files(
        ctx,
        {"pattern": "hello", "file_globs": ["*.txt"], "fire_when": "no_match"},
    )
    assert findings == []


def test_caret_anchor_matches_any_line(tmp_path: Path):
    """Regression: workflow.concurrency_guard's `^concurrency:` clause
    must match a top-level YAML key even when the file starts with a
    different key. Without re.MULTILINE, `^` only anchors at offset 0
    of the whole text and the rule false-positives (fire_when=no_match
    fires even though `concurrency:` is present).
    """
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "release.yml").write_text("name: x\n\nconcurrency:\n  group: w\n")
    ctx = RepoContext(root=tmp_path)
    findings = match_regex_in_files(
        ctx,
        {
            "pattern": r"^concurrency:",
            "file_globs": [".github/workflows/*.yml"],
            "fire_when": "no_match",
        },
    )
    assert findings == [], (
        "expected no fire — `concurrency:` IS present at the start of a line; "
        "without re.MULTILINE the matcher fails to see it and false-positives"
    )


def test_caret_anchor_fires_when_truly_absent(tmp_path: Path):
    """Inverse of the above: `^concurrency:` should still fire when no
    workflow file declares concurrency at the start of any line.
    """
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "release.yml").write_text(
        "name: x\n\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    )
    ctx = RepoContext(root=tmp_path)
    findings = match_regex_in_files(
        ctx,
        {
            "pattern": r"^concurrency:",
            "file_globs": [".github/workflows/*.yml"],
            "fire_when": "no_match",
        },
    )
    assert findings, "expected a no_match finding when concurrency is absent"


def test_case_insensitive_flag_still_works(tmp_path: Path):
    """re.MULTILINE got OR'd in — make sure re.IGNORECASE is still
    honoured when case_insensitive=True is passed.
    """
    (tmp_path / "a.txt").write_text("HELLO WORLD\n")
    ctx = RepoContext(root=tmp_path)
    findings = match_regex_in_files(
        ctx,
        {
            "pattern": "hello",
            "file_globs": ["*.txt"],
            "fire_when": "match",
            "case_insensitive": True,
        },
    )
    assert findings, "expected case-insensitive match on HELLO"
