from agent_readiness.live_scan.eta import EtaConfidence, estimate_eta


def test_no_history_returns_low_confidence_30s_baseline():
    eta = estimate_eta(meta={"scans": []}, remaining_children=10)
    assert eta.minutes == 5
    assert eta.confidence is EtaConfidence.LOW


def test_history_with_per_child_duration_uses_median():
    meta = {
        "scans": [
            {"status": "completed", "per_child_duration_ms_median": 10000},
            {"status": "completed", "per_child_duration_ms_median": 12000},
            {"status": "completed", "per_child_duration_ms_median": 11000},
        ]
    }
    eta = estimate_eta(meta=meta, remaining_children=10)
    assert eta.minutes == 2
    assert eta.confidence is EtaConfidence.HIGH


def test_only_failed_history_falls_back_to_low_confidence():
    meta = {
        "scans": [
            {"status": "failed", "per_child_duration_ms_median": 5000}
        ]
    }
    eta = estimate_eta(meta=meta, remaining_children=4)
    assert eta.confidence is EtaConfidence.LOW
    assert eta.minutes == 2


def test_uses_last_three_only():
    meta = {"scans": [
        {"status": "completed", "per_child_duration_ms_median": 1000},
        {"status": "completed", "per_child_duration_ms_median": 1000},
        {"status": "completed", "per_child_duration_ms_median": 60000},
        {"status": "completed", "per_child_duration_ms_median": 60000},
        {"status": "completed", "per_child_duration_ms_median": 60000},
    ]}
    eta = estimate_eta(meta=meta, remaining_children=2)
    assert eta.minutes == 2
