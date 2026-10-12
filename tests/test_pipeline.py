import pytest

import pipeline
from settings import Settings


def test_run_calls_three_stages_in_order_with_same_ref(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pipeline.crawler_service, "crawl",
                        lambda ref, settings, *, client, log: calls.append(("crawl", ref)))
    monkeypatch.setattr(pipeline.preprocessing_service, "extract",
                        lambda ref, settings, *, llm, log: calls.append(("extract", ref)))
    monkeypatch.setattr(pipeline.scoring_service, "match",
                        lambda ref, settings, *, llm, candidates_dir, refresh, log:
                        calls.append(("match", ref, candidates_dir, refresh)) or "RESULT")
    s = Settings(data_dir=tmp_path, candidates_dir=tmp_path / "c")
    out = pipeline.run("55", s, llm=object(), client=object(), refresh=True, log=lambda m: None)
    assert out == "RESULT"
    assert calls == [("crawl", "55"), ("extract", "55"), ("match", "55", tmp_path / "c", True)]


def test_failed_stage_stops_the_pipeline(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("추출 실패")

    monkeypatch.setattr(pipeline.crawler_service, "crawl", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.preprocessing_service, "extract", boom)
    monkeypatch.setattr(pipeline.scoring_service, "match", lambda *a, **k: pytest.fail("매칭까지 가면 안 됨"))
    with pytest.raises(RuntimeError, match="추출 실패"):
        pipeline.run("55", Settings(data_dir=tmp_path), llm=object(), client=object(), log=lambda m: None)


def test_own_http_client_is_closed(monkeypatch, tmp_path):
    closed = []

    class Client:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(pipeline.crawler_service, "make_client", lambda settings: Client())
    monkeypatch.setattr(pipeline.crawler_service, "crawl", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.preprocessing_service, "extract", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.scoring_service, "match", lambda *a, **k: "R")
    assert pipeline.run("55", Settings(data_dir=tmp_path), llm=object(), log=lambda m: None) == "R"
    assert closed == [True]
