import json

from agent_readiness.live_scan.history import (
    archive_envelope,
    prune_archive,
    read_meta,
    register_scan,
    rotate_log,
)


def test_read_meta_returns_empty_when_file_absent(tmp_path):
    m = read_meta(tmp_path)
    assert m["scans"] == []


def test_register_scan_appends_entry_and_persists(tmp_path):
    register_scan(
        tmp_path,
        workspace_path="/abs/mle",
        workspace_hash="mle-a3f2c1",
        ts="2026-05-25T14-30-12Z",
        status="completed",
        overall=67.4,
    )
    on_disk = json.loads((tmp_path / "meta.json").read_text())
    assert on_disk["workspace_path"] == "/abs/mle"
    assert on_disk["workspace_hash"] == "mle-a3f2c1"
    assert on_disk["scans"][0]["ts"] == "2026-05-25T14-30-12Z"
    assert on_disk["scans"][0]["overall"] == 67.4


def test_archive_envelope_renames_live_to_archive(tmp_path):
    live = tmp_path / "live.json"
    live.write_text('{"status": "completed"}')
    (tmp_path / "archive").mkdir()
    ts = archive_envelope(tmp_path)
    assert not live.exists()
    archived = tmp_path / "archive" / f"{ts}.json"
    assert archived.exists()
    assert json.loads(archived.read_text())["status"] == "completed"


def test_archive_envelope_also_writes_latest_json(tmp_path):
    (tmp_path / "live.json").write_text(
        '{"status": "completed", "overall_score": 50.0}'
    )
    (tmp_path / "archive").mkdir()
    archive_envelope(tmp_path)
    latest = tmp_path / "latest.json"
    assert latest.exists()
    assert json.loads(latest.read_text())["overall_score"] == 50.0


def test_prune_archive_keeps_n_newest_and_soft_deletes_older(tmp_path):
    arc = tmp_path / "archive"
    arc.mkdir()
    names = [
        "2026-01-01T00-00-00Z.json",
        "2026-01-02T00-00-00Z.json",
        "2026-01-03T00-00-00Z.json",
        "2026-01-04T00-00-00Z.json",
        "2026-01-05T00-00-00Z.json",
    ]
    for n in names:
        (arc / n).write_text("{}")
    prune_archive(tmp_path, keep=3)
    remaining = sorted(p.name for p in arc.iterdir() if p.is_file())
    assert remaining == names[-3:]
    trashed = sorted(p.name for p in (arc / ".trash").iterdir())
    assert trashed == names[:2]


def test_prune_archive_hard_deletes_trash_on_subsequent_prune(tmp_path):
    arc = tmp_path / "archive"
    trash = arc / ".trash"
    trash.mkdir(parents=True)
    (trash / "old.json").write_text("{}")
    prune_archive(tmp_path, keep=3)
    assert not (trash / "old.json").exists()


def test_rotate_log_truncates_and_creates_dot1(tmp_path):
    log = tmp_path / "scan.log"
    log.write_text("x" * 200)
    rotate_log(log, max_bytes=100)
    assert (tmp_path / "scan.log.1").read_text() == "x" * 200
    assert log.read_text() == ""


def test_rotate_log_noop_when_under_cap(tmp_path):
    log = tmp_path / "scan.log"
    log.write_text("small")
    rotate_log(log, max_bytes=100)
    assert log.read_text() == "small"
    assert not (tmp_path / "scan.log.1").exists()
