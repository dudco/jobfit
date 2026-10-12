from types import SimpleNamespace

import pytest

import pipeline
from settings import Settings


IMAGE_SNAPSHOT = SimpleNamespace(images=["00.png"], body_text_length=0)


def test_run_calls_three_stages_in_order_with_same_ref(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pipeline.crawler_service, "crawl",
                        lambda ref, settings, *, client, log: calls.append(("crawl", ref)) or IMAGE_SNAPSHOT)
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

    monkeypatch.setattr(pipeline.crawler_service, "crawl", lambda *a, **k: IMAGE_SNAPSHOT)
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
    monkeypatch.setattr(pipeline.crawler_service, "crawl", lambda *a, **k: IMAGE_SNAPSHOT)
    monkeypatch.setattr(pipeline.preprocessing_service, "extract", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.scoring_service, "match", lambda *a, **k: "R")
    assert pipeline.run("55", Settings(data_dir=tmp_path), llm=object(), log=lambda m: None) == "R"
    assert closed == [True]


def test_posting_without_body_images_stops_after_crawl_with_reason(monkeypatch, tmp_path):
    """텍스트 공고(본문 이미지 없음)는 추출·매칭으로 넘기지 않고 이유를 알린다 (ADR-0008)."""
    text_posting = SimpleNamespace(images=[], body_text_length=1722)
    monkeypatch.setattr(pipeline.crawler_service, "crawl", lambda *a, **k: text_posting)
    monkeypatch.setattr(pipeline.preprocessing_service, "extract", lambda *a, **k: pytest.fail("추출하면 안 됨"))
    monkeypatch.setattr(pipeline.scoring_service, "match", lambda *a, **k: pytest.fail("매칭하면 안 됨"))
    with pytest.raises(RuntimeError) as e:
        pipeline.run("55226797", Settings(data_dir=tmp_path), llm=object(), client=object(), log=lambda m: None)
    assert "이미지 공고가 아님" in str(e.value) and "1722자" in str(e.value) and "본문 이미지가 없음" in str(e.value)
