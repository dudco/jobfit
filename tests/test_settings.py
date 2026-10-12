from jobfit.settings import load_settings

KEYS = ("JOBFIT_DATA_DIR", "JOBFIT_REQUEST_INTERVAL")


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JOBFIT_REQUEST_INTERVAL", "0")
    s = load_settings()
    assert s.data_dir == tmp_path
    assert s.request_interval == 0.0


def test_defaults(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert s.data_dir.name == "data"
    assert s.request_interval == 1.5
    assert "Mozilla" in s.user_agent
