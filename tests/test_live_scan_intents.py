import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_readiness.live_scan.intents import create_intent, intents_root


def test_create_start_intent_persists_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    rec = create_intent("start", path="/abs/ws")
    assert rec["action"] == "start"
    assert rec["path"] == "/abs/ws"
    assert rec["status"] == "pending"
    assert rec["id"].startswith("int-")
    f = intents_root() / f"{rec['id']}.json"
    assert f.is_file()


def test_create_stop_intent_requires_scan_id(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    rec = create_intent("stop", scan_id="Documents-ab12cd")
    assert rec["action"] == "stop"
    assert rec["scan_id"] == "Documents-ab12cd"


def test_create_start_without_path_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError, match="path"):
        create_intent("start")


def test_create_stop_without_scan_id_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError, match="scan_id"):
        create_intent("stop")


def test_create_unknown_action_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError, match="action"):
        create_intent("frobnicate", path="/x")


def test_list_intents_newest_first_and_status_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan.intents import list_intents
    a = create_intent("start", path="/a")
    b = create_intent("start", path="/b")
    ids_all = [r["id"] for r in list_intents()]
    assert ids_all[0] == b["id"]
    assert a["id"] in ids_all
    pending = list_intents(status="pending")
    assert {r["id"] for r in pending} == {a["id"], b["id"]}
    assert list_intents(status="done") == []


def test_claim_transitions_pending_to_claimed_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan.intents import claim_intent
    rec = create_intent("start", path="/a")
    claimed = claim_intent(rec["id"])
    assert claimed is not None
    assert claimed["status"] == "claimed"
    assert claimed["claimed_at"] is not None
    assert claim_intent(rec["id"]) is None


def test_claim_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan.intents import claim_intent
    assert claim_intent("int-nope00") is None


def test_claim_reclaims_stale_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan import intents as I
    rec = I.create_intent("start", path="/a")
    I.claim_intent(rec["id"])
    f = I.intents_root() / f"{rec['id']}.json"
    data = json.loads(f.read_text())
    data["claimed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    f.write_text(json.dumps(data))
    again = I.claim_intent(rec["id"])
    assert again is not None
    assert again["status"] == "claimed"


def test_ack_sets_terminal_status_and_result(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan.intents import ack_intent, claim_intent
    rec = create_intent("start", path="/a")
    claim_intent(rec["id"])
    done = ack_intent(rec["id"], "done", result={"dashboard_url": "http://x"})
    assert done["status"] == "done"
    assert done["result"] == {"dashboard_url": "http://x"}


def test_ack_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan.intents import ack_intent
    assert ack_intent("int-nope00", "done") is None


def test_ack_rejects_bad_status(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan.intents import ack_intent
    rec = create_intent("stop", scan_id="s")
    with pytest.raises(ValueError, match="status"):
        ack_intent(rec["id"], "banana")


def test_prune_keeps_recent_terminal_intents(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from agent_readiness.live_scan import intents as I
    ids = []
    for i in range(3):
        r = I.create_intent("stop", scan_id=f"s{i}")
        I.claim_intent(r["id"])
        I.ack_intent(r["id"], "done")
        f = I.intents_root() / f"{r['id']}.json"
        d = json.loads(f.read_text())
        d["created_at"] = f"2026-06-0{i + 1}T00:00:00+00:00"
        f.write_text(json.dumps(d))
        ids.append(r["id"])
    I.prune_intents(keep=2)
    remaining = {r["id"] for r in I.list_intents()}
    assert ids[0] not in remaining
    assert ids[2] in remaining
