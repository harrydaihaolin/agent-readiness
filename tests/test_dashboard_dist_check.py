"""Freshness guard for the bundled dashboard dist.

Regression coverage for the bug where ``_dashboard_dist`` was committed
from a build that PREDATED the onboarding wizard, so the engine emitted
``/#/onboarding/<scan_id>`` URLs that the shipped SPA had no route for —
the dashboard rendered only its top/bottom chrome with a blank body.
"""
from pathlib import Path

from agent_readiness.dashboard_dist_check import find_dist_problems
from agent_readiness.live_scan.server import dashboard_dist_path


def _write_dist(root: Path, js_body: str, *, with_index: bool = True) -> Path:
    dist = root / "_dashboard_dist"
    (dist / "assets").mkdir(parents=True)
    if with_index:
        (dist / "index.html").write_text(
            '<!doctype html><script src="/assets/index-abc.js"></script>'
        )
    (dist / "assets" / "index-abc.js").write_text(js_body)
    return dist


def test_flags_bundle_missing_the_onboarding_route(tmp_path):
    # A bundle that only knows /workspaces/ (the pre-onboarding build) is
    # exactly the stale artifact that shipped the bug.
    dist = _write_dist(tmp_path, js_body='router("/workspaces/:scanId")')
    problems = find_dist_problems(dist)
    assert problems
    assert any("/onboarding/" in p for p in problems)
    assert any("make dashboard" in p for p in problems)


def test_passes_for_a_complete_bundle(tmp_path):
    dist = _write_dist(
        tmp_path,
        js_body='router("/onboarding/:scanId");router("/workspaces/:scanId")',
    )
    assert find_dist_problems(dist) == []


def test_flags_missing_index_html(tmp_path):
    dist = _write_dist(tmp_path, js_body="anything", with_index=False)
    problems = find_dist_problems(dist)
    assert problems
    assert any("index.html" in p for p in problems)


def test_packaged_dashboard_dist_is_fresh():
    """The dist actually shipped in the package must satisfy the guard —
    this is the check that would have caught the original bug."""
    assert find_dist_problems(dashboard_dist_path()) == []
