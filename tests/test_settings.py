from settings import load_settings

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


PREP_KEYS = ("JOBFIT_VISION_MODEL", "JOBFIT_TEXT_MODEL", "JOBFIT_SLICE_HEIGHT", "JOBFIT_MAX_WIDTH",
             "JOBFIT_JUDGE_MODEL")


def test_preprocessing_settings_from_env(monkeypatch):
    monkeypatch.setenv("JOBFIT_VISION_MODEL", "v-model")
    monkeypatch.setenv("JOBFIT_TEXT_MODEL", "t-model")
    monkeypatch.setenv("JOBFIT_SLICE_HEIGHT", "0")
    monkeypatch.setenv("JOBFIT_MAX_WIDTH", "900")
    s = load_settings(dotenv_path=None)
    assert (s.vision_model, s.text_model, s.slice_height, s.max_width) == ("v-model", "t-model", 0, 900)


def test_preprocessing_defaults(monkeypatch, tmp_path):
    for k in PREP_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("JOBFIT_DATA_DIR", str(tmp_path))
    s = load_settings(dotenv_path=None)
    assert s.vision_model and s.text_model
    assert (s.slice_height, s.max_width) == (1200, 1000)
    assert s.llm_cache_dir == tmp_path / "cache" / "llm"


def test_judge_model_from_env_and_default(monkeypatch):
    for k in PREP_KEYS:
        monkeypatch.delenv(k, raising=False)
    assert load_settings(dotenv_path=None).judge_model == "gpt-4.1"
    monkeypatch.setenv("JOBFIT_JUDGE_MODEL", "j-model")
    assert load_settings(dotenv_path=None).judge_model == "j-model"
