"""Tests for the per-check progress visualizer.

Contract under test:
- `enabled=False` is a true no-op (no stderr writes, no rich import).
- Non-TTY stderr auto-disables (the CLI must stay headless-clean).
- The advance loop runs without crashing for either rich or plain mode.
- Driving `scan` via CliRunner (always non-TTY) leaves stderr empty of
  progress chrome — this is the load-bearing guarantee for piping and
  snapshot tests.
"""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_readiness.renderers.progress import ScanProgress


_FIXTURES = Path(__file__).parent / "fixtures"


class ScanProgressDisabled(unittest.TestCase):

    def test_enabled_false_writes_nothing_to_stderr(self):
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            with ScanProgress(total=3, enabled=False) as p:
                self.assertFalse(p.enabled)
                p.advance("a")
                p.advance("b")
                p.advance("c")
        self.assertEqual(buf.getvalue(), "")

    def test_non_tty_stderr_auto_disables(self):
        buf = io.StringIO()  # StringIO.isatty() is False
        with patch.object(sys, "stderr", buf):
            with ScanProgress(total=2) as p:
                self.assertFalse(p.enabled)
                p.advance("foo")
        self.assertEqual(buf.getvalue(), "")

    def test_zero_total_is_safe(self):
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            with ScanProgress(total=0, enabled=False):
                pass
        self.assertEqual(buf.getvalue(), "")


class ScanProgressPlainFallback(unittest.TestCase):
    """Plain-mode rendering when stderr is a fake-TTY without rich.

    We force the 'plain' mode by faking ``sys.stderr.isatty`` and shadowing
    ``rich`` in ``sys.modules`` so the import inside ScanProgress fails.
    This isolates the fallback path even on machines that do have rich.
    """

    def _make_tty_buffer(self) -> io.StringIO:
        buf = io.StringIO()
        buf.isatty = lambda: True  # type: ignore[method-assign]
        return buf

    def test_plain_mode_writes_per_check_lines_then_clears(self):
        buf = self._make_tty_buffer()
        # Force ImportError for `import rich` inside ScanProgress.
        with patch.dict(sys.modules, {"rich": None, "rich.progress": None}):
            with patch.object(sys, "stderr", buf):
                with ScanProgress(total=3) as p:
                    self.assertTrue(p.enabled)
                    p.advance("alpha")
                    p.advance("beta")
                    p.advance("gamma")
        out = buf.getvalue()
        self.assertIn("[1/3] alpha", out)
        self.assertIn("[2/3] beta", out)
        self.assertIn("[3/3] gamma", out)
        # The final clear sequence wipes the line: a \r followed by spaces
        # and another \r. Check that the last meaningful frame did get
        # overwritten by checking it ends with a clearing \r.
        self.assertTrue(out.endswith("\r"))


class ScanProgressViaCli(unittest.TestCase):
    """End-to-end: invoking `scan` via CliRunner must keep stdout clean.

    CliRunner stderr/stdout are non-TTY ``StringIO`` buffers, so
    ScanProgress should auto-disable. The report stays the only artefact
    on stdout.
    """

    def test_scan_with_progress_default_no_pollution(self):
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["scan", str(_FIXTURES / "good")])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("AI Readiness", result.output)
        self.assertNotIn("scanning", result.output)

    def test_scan_with_no_progress_flag(self):
        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        result = runner.invoke(
            cli, ["scan", str(_FIXTURES / "good"), "--no-progress"]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("AI Readiness", result.output)
        self.assertNotIn("scanning", result.output)

    def test_scan_json_keeps_stdout_pure(self):
        """`--json` must not be contaminated with progress glyphs."""
        import json

        from click.testing import CliRunner
        from agent_readiness.cli import cli

        runner = CliRunner()
        result = runner.invoke(
            cli, ["scan", str(_FIXTURES / "good"), "--json"]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        # Whole stdout must parse as JSON — proves no progress bleed-through.
        parsed = json.loads(result.output)
        self.assertIn("overall_score", parsed)


if __name__ == "__main__":
    unittest.main()
