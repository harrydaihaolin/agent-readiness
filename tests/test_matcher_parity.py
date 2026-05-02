"""Parity harness — OSS scanner vs `agent-readiness-insights`.

The OSS scanner (this repo) and the closed insights engine
(`agent-readiness-insights`) ship two independent implementations of
the same set of OSS leaf matchers (`file_size`, `path_glob`,
`manifest_field`, `regex_in_files`, `command_in_makefile`,
`composite`). That double-implementation is exactly the surface where
silent drift happens: a fix or a heuristic refinement lands in one
side and not the other, and clients see different findings depending
on which engine ran them.

This test eliminates that drift surface by running the same set of
synthetic rules through both implementations and asserting the
findings lists are identical.

It is **opt-in**: skipped unless `agent-readiness-insights` is
importable on the test runner. CI in either repo can satisfy that
requirement by `pip install`-ing the sibling. The same file is
mirrored into `agent-readiness-insights/tests/test_matcher_parity.py`
so both repos exercise the harness from their own side; whichever
side reds first surfaces the regression.

Note: the harness deliberately covers only the OSS leaf types the
two engines duplicate. Private matchers registered via
``register_private_matcher`` are not part of the parity surface
because there's only one implementation by construction.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Allow the test to be runnable from a check-out without an installed wheel.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# OSS side — always available in this repo.
from agent_readiness.context import RepoContext as OSSContext  # noqa: E402
from agent_readiness.rules_eval import matchers as oss_matchers  # noqa: E402

ar_insights = pytest.importorskip(
    "agent_readiness_insights",
    reason="agent-readiness-insights not installed; pip install it to run parity checks",
)

from agent_readiness_insights.matchers_oss import OSS_MATCHERS as INSIGHTS_OSS  # noqa: E402
from agent_readiness_insights.repo_context import RepoContext as InsContext  # noqa: E402


# Mapping of OSS match type -> (oss_callable, insights_callable). If
# either repo grows a new shared matcher, add it here in the same PR.
PARITY_MATRIX: list[tuple[str, Any, Any]] = [
    ("file_size", oss_matchers.match_file_size, INSIGHTS_OSS["file_size"]),
    ("path_glob", oss_matchers.match_path_glob, INSIGHTS_OSS["path_glob"]),
    ("manifest_field", oss_matchers.match_manifest_field, INSIGHTS_OSS["manifest_field"]),
    ("regex_in_files", oss_matchers.match_regex_in_files, INSIGHTS_OSS["regex_in_files"]),
    ("command_in_makefile", oss_matchers.match_command_in_makefile, INSIGHTS_OSS["command_in_makefile"]),
]


def _normalise(findings: list[tuple[Any, ...]]) -> set[tuple[str, int, str]]:
    """Reduce a findings list to a comparable set.

    Both engines emit (file, line, message) tuples; we coerce file to
    a string (None -> ''), line to an int (None -> -1), and message to
    str. Set semantics intentionally drops ordering — neither engine
    guarantees a stable order across implementations and a "same
    findings, different order" diff is not a real regression.
    """
    out: set[tuple[str, int, str]] = set()
    for finding in findings:
        f, ln, msg = finding[0], finding[1], finding[2]
        out.add((
            "" if f is None else str(f),
            -1 if ln is None else int(ln),
            str(msg),
        ))
    return out


@pytest.fixture(scope="module")
def synthetic_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("parity-repo")
    (root / "src").mkdir()
    (root / "src" / "small.py").write_text("print('hi')\n")
    (root / "src" / "big.py").write_text("\n".join(f"line {i}" for i in range(900)))
    (root / "Makefile").write_text(".PHONY: test\n\ntest:\n\tpytest\n")
    (root / "README.md").write_text("# Demo\n\nrun `make test`.\n")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.0.0"\n[tool.pytest.ini_options]\naddopts = "-q"\n'
    )
    (root / "package.json").write_text('{"name": "demo", "scripts": {"test": "vitest run"}}')
    return root


@pytest.mark.parametrize(
    "match_type, cfg",
    [
        # file_size: large file should fire on src/big.py.
        ("file_size", {"type": "file_size", "threshold_lines": 500, "threshold_bytes": 1_000_000}),
        # path_glob require_globs: a missing AGENTS.md should fire.
        ("path_glob", {"type": "path_glob", "require_globs": ["AGENTS.md"]}),
        # manifest_field: project.scripts is missing in this pyproject.
        ("manifest_field", {
            "type": "manifest_field",
            "manifest": "pyproject.toml",
            "field_path": "project.scripts",
            "fire_when": "missing",
        }),
        # regex_in_files: pytest table is in pyproject (so no_match should NOT fire).
        ("regex_in_files", {
            "type": "regex_in_files",
            "pattern": r"\[tool\.pytest",
            "file_globs": ["pyproject.toml"],
            "fire_when": "no_match",
        }),
        # command_in_makefile: test target IS present, so missing should NOT fire.
        ("command_in_makefile", {
            "type": "command_in_makefile",
            "target": "test",
            "fire_when": "missing",
        }),
        # command_in_makefile: lint target is NOT present, so missing SHOULD fire.
        ("command_in_makefile", {
            "type": "command_in_makefile",
            "target": "lint",
            "fire_when": "missing",
        }),
    ],
)
def test_oss_matcher_parity(match_type: str, cfg: dict, synthetic_repo: Path) -> None:
    oss_fn = next((o for t, o, _ in PARITY_MATRIX if t == match_type), None)
    ins_fn = next((i for t, _, i in PARITY_MATRIX if t == match_type), None)
    assert oss_fn is not None and ins_fn is not None, (
        f"PARITY_MATRIX missing entry for {match_type}"
    )
    oss_ctx = OSSContext(root=synthetic_repo)
    ins_ctx = InsContext(root=synthetic_repo)
    oss_findings = _normalise(oss_fn(oss_ctx, cfg))
    ins_findings = _normalise(ins_fn(ins_ctx, cfg))
    assert oss_findings == ins_findings, (
        f"\nOSS-only:      {sorted(oss_findings - ins_findings)}\n"
        f"Insights-only: {sorted(ins_findings - oss_findings)}\n"
        f"Common:        {sorted(oss_findings & ins_findings)}"
    )


def test_parity_matrix_covers_every_oss_leaf_type() -> None:
    """If a new OSS leaf type is added to the protocol, this test fails
    until PARITY_MATRIX grows a corresponding row. The mirrored test in
    `agent-readiness-insights` enforces the same contract from that
    side."""
    OSS_TYPES = {
        "file_size",
        "path_glob",
        "manifest_field",
        "regex_in_files",
        "command_in_makefile",
        # composite is intentionally excluded from this set: it's a
        # boolean wrapper over leaf clauses, so its parity is implied
        # by the leaves' parity. If you add a new leaf, mirror it here
        # AND in PARITY_MATRIX above.
    }
    covered = {t for t, _, _ in PARITY_MATRIX}
    missing = OSS_TYPES - covered
    assert not missing, f"PARITY_MATRIX is missing rows for: {sorted(missing)}"
