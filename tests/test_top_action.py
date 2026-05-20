"""EXP-4 tests: per-repo top_action pin.

Covers the priority sort (severity > pillar > weight), serialization
round-trip, and the coverage invariant ("any repo with >=1 measured
finding gets a non-null top_action").
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_readiness.models import (
    CheckResult,
    Finding,
    Pillar,
    Severity,
)
from agent_readiness.scorer import compute_top_action, score


def _make_finding(
    check_id: str,
    pillar: Pillar,
    severity: Severity = Severity.WARN,
    message: str = "noise",
    *,
    fix_hint: str | None = None,
    action: dict | None = None,
    verify: dict | None = None,
) -> Finding:
    return Finding(
        check_id=check_id,
        pillar=pillar,
        message=message,
        severity=severity,
        fix_hint=fix_hint,
        action=action,
        verify=verify,
    )


def _make_check(
    check_id: str,
    pillar: Pillar,
    findings: list[Finding],
    *,
    weight: float = 1.0,
    score: float = 50.0,
    not_measured: bool = False,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        pillar=pillar,
        score=score,
        weight=weight,
        not_measured=not_measured,
        findings=findings,
    )


class TopActionPriorityTest(unittest.TestCase):
    """The priority sort: severity > pillar > weight desc > check_id."""

    def test_severity_wins_over_pillar(self):
        """An ERROR cognitive_load finding beats a WARN flow finding —
        severity is the dominant key."""
        results = [
            _make_check(
                "flow.warn",
                Pillar.FLOW,
                [_make_finding("flow.warn", Pillar.FLOW, Severity.WARN)],
            ),
            _make_check(
                "cog.error",
                Pillar.COGNITIVE_LOAD,
                [_make_finding("cog.error", Pillar.COGNITIVE_LOAD, Severity.ERROR)],
            ),
        ]
        report = score(Path("/tmp/x"), results)
        self.assertIsNotNone(report.top_action)
        self.assertEqual(report.top_action["check_id"], "cog.error")
        self.assertEqual(report.top_action["severity"], "error")

    def test_pillar_breaks_ties_within_severity(self):
        """Same severity (WARN), pillar order picks FLOW > FEEDBACK >
        SAFETY > COGNITIVE_LOAD."""
        results = [
            _make_check(
                "cog.warn",
                Pillar.COGNITIVE_LOAD,
                [_make_finding("cog.warn", Pillar.COGNITIVE_LOAD, Severity.WARN)],
            ),
            _make_check(
                "feedback.warn",
                Pillar.FEEDBACK,
                [_make_finding("feedback.warn", Pillar.FEEDBACK, Severity.WARN)],
            ),
            _make_check(
                "flow.warn",
                Pillar.FLOW,
                [_make_finding("flow.warn", Pillar.FLOW, Severity.WARN)],
            ),
            _make_check(
                "safety.warn",
                Pillar.SAFETY,
                [_make_finding("safety.warn", Pillar.SAFETY, Severity.WARN)],
            ),
        ]
        report = score(Path("/tmp/x"), results)
        self.assertEqual(report.top_action["check_id"], "flow.warn")

    def test_weight_breaks_ties_within_pillar(self):
        """Same severity + same pillar, higher-weight rule wins."""
        results = [
            _make_check(
                "flow.low_weight",
                Pillar.FLOW,
                [_make_finding("flow.low_weight", Pillar.FLOW, Severity.WARN)],
                weight=0.5,
            ),
            _make_check(
                "flow.high_weight",
                Pillar.FLOW,
                [_make_finding("flow.high_weight", Pillar.FLOW, Severity.WARN)],
                weight=2.0,
            ),
        ]
        report = score(Path("/tmp/x"), results)
        self.assertEqual(report.top_action["check_id"], "flow.high_weight")

    def test_check_id_breaks_ties_at_the_floor(self):
        """Same severity + same pillar + same weight: stable lexical
        sort on check_id keeps top_action deterministic across scans."""
        results = [
            _make_check(
                "flow.b",
                Pillar.FLOW,
                [_make_finding("flow.b", Pillar.FLOW, Severity.WARN)],
            ),
            _make_check(
                "flow.a",
                Pillar.FLOW,
                [_make_finding("flow.a", Pillar.FLOW, Severity.WARN)],
            ),
        ]
        report = score(Path("/tmp/x"), results)
        self.assertEqual(report.top_action["check_id"], "flow.a")

    def test_safety_error_beats_flow_warn(self):
        """Severity is dominant: a safety error goes top even though
        flow has a higher pillar rank."""
        results = [
            _make_check(
                "flow.warn",
                Pillar.FLOW,
                [_make_finding("flow.warn", Pillar.FLOW, Severity.WARN)],
            ),
            _make_check(
                "safety.error",
                Pillar.SAFETY,
                [_make_finding("safety.error", Pillar.SAFETY, Severity.ERROR)],
            ),
        ]
        report = score(Path("/tmp/x"), results)
        self.assertEqual(report.top_action["check_id"], "safety.error")
        self.assertEqual(report.top_action["pillar"], "safety")


class TopActionPayloadTest(unittest.TestCase):
    """The top_action dict shape."""

    def test_carries_action_and_verify_for_v2(self):
        action_obj = {
            "kind": "create_file",
            "path": "Makefile",
            "template": "test:\n\tpytest tests/\n",
        }
        verify_obj = {"command": "make -n test", "description": "make resolves test"}
        results = [
            _make_check(
                "feedback.no_make",
                Pillar.FEEDBACK,
                [
                    _make_finding(
                        "feedback.no_make",
                        Pillar.FEEDBACK,
                        Severity.WARN,
                        message="missing Makefile target",
                        fix_hint="add a `test` target",
                        action=action_obj,
                        verify=verify_obj,
                    )
                ],
            )
        ]
        report = score(Path("/tmp/x"), results)
        self.assertEqual(report.top_action["action"], action_obj)
        self.assertEqual(report.top_action["verify"], verify_obj)
        self.assertEqual(report.top_action["fix_hint"], "add a `test` target")

    def test_v1_finding_has_top_action_without_action_block(self):
        """Coverage gate: legacy v1 rules (no action object) still
        get pinned. The dict simply omits action/verify keys."""
        results = [
            _make_check(
                "flow.legacy",
                Pillar.FLOW,
                [
                    _make_finding(
                        "flow.legacy",
                        Pillar.FLOW,
                        Severity.WARN,
                        message="legacy v1 rule",
                        fix_hint="freeform prose only",
                    )
                ],
            )
        ]
        report = score(Path("/tmp/x"), results)
        self.assertIsNotNone(report.top_action)
        self.assertEqual(report.top_action["check_id"], "flow.legacy")
        self.assertNotIn("action", report.top_action)
        self.assertNotIn("verify", report.top_action)
        self.assertEqual(report.top_action["fix_hint"], "freeform prose only")


class TopActionCoverageTest(unittest.TestCase):
    """The EXP-4 coverage invariant: any repo with >=1 finding gets a pin."""

    def test_zero_findings_means_no_top_action(self):
        results = [
            _make_check("flow.clean", Pillar.FLOW, [], score=100.0),
        ]
        report = score(Path("/tmp/x"), results)
        self.assertIsNone(report.top_action)

    def test_skipped_check_does_not_contribute_to_top_action(self):
        """A `not_measured` check's findings (pathological but
        possible) must not be picked as the pin."""
        results = [
            _make_check(
                "feedback.skipped",
                Pillar.FEEDBACK,
                [_make_finding("feedback.skipped", Pillar.FEEDBACK, Severity.ERROR)],
                not_measured=True,
            ),
            _make_check(
                "flow.real",
                Pillar.FLOW,
                [_make_finding("flow.real", Pillar.FLOW, Severity.WARN)],
            ),
        ]
        report = score(Path("/tmp/x"), results)
        self.assertEqual(report.top_action["check_id"], "flow.real")

    def test_at_least_one_finding_means_top_action_present(self):
        """The coverage gate."""
        results = [
            _make_check(
                "cog.lonely",
                Pillar.COGNITIVE_LOAD,
                [_make_finding("cog.lonely", Pillar.COGNITIVE_LOAD, Severity.INFO)],
            ),
        ]
        report = score(Path("/tmp/x"), results)
        self.assertIsNotNone(report.top_action)


class TopActionSerializationTest(unittest.TestCase):
    """top_action survives Report.to_dict() and JSON round-trip."""

    def test_to_dict_includes_top_action(self):
        results = [
            _make_check(
                "flow.x",
                Pillar.FLOW,
                [_make_finding("flow.x", Pillar.FLOW, Severity.ERROR)],
            )
        ]
        report = score(Path("/tmp/x"), results)
        d = report.to_dict()
        self.assertIn("top_action", d)
        self.assertEqual(d["top_action"]["check_id"], "flow.x")

    def test_to_dict_omits_top_action_when_none(self):
        report = score(Path("/tmp/x"), [_make_check("flow.clean", Pillar.FLOW, [], score=100.0)])
        d = report.to_dict()
        self.assertNotIn("top_action", d)


class ComputeTopActionDirectTest(unittest.TestCase):
    """Direct call (not via score()) so we test the function in isolation."""

    def test_returns_none_for_empty_pillar_scores(self):
        from agent_readiness.models import Report

        report = Report(repo_path=Path("/tmp/x"), overall_score=100.0)
        self.assertIsNone(compute_top_action(report))


if __name__ == "__main__":
    unittest.main()
