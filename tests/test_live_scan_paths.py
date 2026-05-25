
from agent_readiness.live_scan.paths import scan_dir, scans_root, workspace_hash


def test_workspace_hash_human_readable_prefix_plus_sha_suffix(tmp_path):
    ws = tmp_path / "mle"
    ws.mkdir()
    h = workspace_hash(ws)
    assert h.startswith("mle-")
    suffix = h.split("-", 1)[1]
    assert len(suffix) == 6
    assert all(c in "0123456789abcdef" for c in suffix)


def test_workspace_hash_deterministic(tmp_path):
    ws = tmp_path / "mle"
    ws.mkdir()
    assert workspace_hash(ws) == workspace_hash(ws.resolve())


def test_workspace_hash_differs_for_different_paths(tmp_path):
    a = tmp_path / "a" / "mle"
    b = tmp_path / "b" / "mle"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert workspace_hash(a) != workspace_hash(b)


def test_scan_dir_under_user_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    ws = tmp_path / "mle"
    ws.mkdir()
    d = scan_dir(ws)
    assert d == tmp_path / ".agent-readiness" / "scans" / workspace_hash(ws)


def test_scans_root_is_home_relative(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert scans_root() == tmp_path / ".agent-readiness" / "scans"
