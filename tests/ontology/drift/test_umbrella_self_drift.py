"""Umbrella self-drift smoke test — dogfood guardrail."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

UMBRELLA = Path("/Users/haolin.dai/Documents/agent-readiness_project")
MANIFEST_ONTOLOGY = UMBRELLA / "agent-readiness-manifest" / "ontology"


@pytest.mark.skipif(not MANIFEST_ONTOLOGY.is_dir(), reason="umbrella manifest not available")
def test_umbrella_self_drift_is_acceptable():
    """Run drift on the umbrella's actual ontology. The umbrella's own
    ontology should never reach block-severity drift."""
    from agent_readiness.ontology.drift.detect import detect_drift

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        os.symlink(MANIFEST_ONTOLOGY, tmp_path / "ontology")
        for child in UMBRELLA.iterdir():
            if (child / ".git").exists():
                os.symlink(child, tmp_path / child.name)
        report = detect_drift(tmp_path)
        assert report.severity_level in ("clean", "warn"), (
            f"Umbrella's own drift level is {report.severity_level}: {report.deltas}"
        )
