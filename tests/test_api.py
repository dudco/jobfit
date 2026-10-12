import dataclasses

from fastapi.testclient import TestClient
from PIL import Image

import api
from preprocessing.criteria import criteria_dir, save_criteria

from .fakes import FakeLLM
from .scoring_fixtures import make_criteria
from .test_scoring_service import REQS, by_declaration, person, write_candidates
from .test_scoring_service import settings as make_settings


def client_for(tmp_path, llm=None, with_criteria=True):
    d = write_candidates(tmp_path, person("a", ["야간근무 가능"]), person("b", ["야간근무 불가"], label="mismatch"))
    s = dataclasses.replace(make_settings(tmp_path), candidates_dir=d)
    if with_criteria:
        save_criteria(criteria_dir(s.data_dir, "saramin", "55"), make_criteria(REQS))
    return TestClient(api.create_app(s, llm=llm or FakeLLM(structured=[by_declaration] * 2))), s


def test_postings_criteria_and_result_lifecycle(tmp_path):
    c, _ = client_for(tmp_path)
    [p] = c.get("/api/postings").json()
    assert (p["posting_id"], p["must"], p["preferred"], p["matched_at"]) == ("55", 1, 2, None)
    assert c.get("/api/postings/55/criteria").json()["title"] == "테스트 공고"
    assert c.get("/api/postings/55/result").status_code == 404
    r = c.post("/api/postings/55/match", json={"refresh": False})
    assert r.status_code == 200 and [x["candidate_id"] for x in r.json()["candidates"]] == ["a", "b"]
    assert c.get("/api/postings/55/result").json() == r.json()
    assert c.get("/api/postings").json()[0]["matched_at"]


def test_rescore_endpoint_does_not_call_llm_or_save(tmp_path):
    llm = FakeLLM(structured=[by_declaration] * 2)
    c, _ = client_for(tmp_path, llm)
    saved = c.post("/api/postings/55/match", json={}).json()
    calls = len(llm.calls)
    r = c.post("/api/postings/55/rescore", json={"must_share": 0.5, "gate": 1.0, "partial": 0.5, "unknown": 0.5})
    assert r.status_code == 200 and r.json()["weights"]["must_share"] == 0.5
    assert len(llm.calls) == calls and c.get("/api/postings/55/result").json() == saved


def test_service_errors_become_400_and_missing_404(tmp_path):
    c, _ = client_for(tmp_path, with_criteria=False)
    assert c.get("/api/postings/55/criteria").status_code == 404
    r = c.post("/api/postings/55/match", json={})
    assert r.status_code == 400 and "jobfit extract 55" in r.json()["detail"]
    assert c.post("/api/run", json={"ref": "잘못된 주소"}).status_code == 400


def test_run_endpoint_uses_pipeline(monkeypatch, tmp_path):
    import pipeline

    from .test_result import sample

    seen = []
    monkeypatch.setattr(pipeline, "run",
                        lambda ref, settings, *, llm, refresh, log: seen.append((ref, refresh)) or sample())
    c, _ = client_for(tmp_path)
    url = "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=55"
    r = c.post("/api/run", json={"ref": url, "refresh": True})
    assert r.status_code == 200 and seen == [(url, True)]
    assert r.json()["candidates"][0]["candidate_id"] == "c1"


def test_slice_image_served_by_transcript_order(tmp_path):
    c, s = client_for(tmp_path)
    slices = criteria_dir(s.data_dir, "saramin", "55") / "slices"
    slices.mkdir()
    for name, color in (("00_00.png", "red"), ("00_01.png", "blue")):
        Image.new("RGB", (4, 4), color).save(slices / name)
    r = c.get("/api/postings/55/slices/1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert c.get("/api/postings/55/slices/2").status_code == 404


def test_candidates_view_separates_evaluation_label(tmp_path):
    c, _ = client_for(tmp_path)
    views = {v["id"]: v for v in c.get("/api/candidates").json()}
    assert views["b"]["label"] == "mismatch" and views["b"]["target_posting"] == "55"
    assert all("mismatch" not in line for line in views["b"]["lines"])
    assert "[자기 신고] 야간근무 불가" in views["b"]["lines"]


def test_index_page_served(tmp_path):
    c, _ = client_for(tmp_path)
    r = c.get("/")
    assert r.status_code == 200 and "jobfit" in r.text


def test_flags_endpoint_explains_codes(tmp_path):
    c, _ = client_for(tmp_path)
    flags = c.get("/api/flags").json()
    assert flags["quote_not_found"]["label"] == "근거 인용 없음" and flags["quote_spliced"]["severity"] == "info"


def _text_snapshot(s, posting_id, images=()):
    from crawler.snapshot import PostingSnapshot, SourceRef, StoredFile, save_snapshot, snapshot_dir
    snap = PostingSnapshot(
        source=SourceRef(site="saramin", posting_id=posting_id, url=f"https://saramin/{posting_id}"),
        fetched_at="2026-10-12T00:00:00+00:00", title=f"텍스트 공고 {posting_id}",
        detail_html=StoredFile(path="detail.html", sha256="x", bytes=1), images=list(images),
        body_text_length=1722, is_image_posting=False)
    save_snapshot(snapshot_dir(s.data_dir, "saramin", posting_id), snap)


def test_unprocessable_postings_are_hidden_from_main_list_and_listed_separately(tmp_path):
    c, s = client_for(tmp_path)
    _text_snapshot(s, "77")                                            # 수집만 됨 — 본문 이미지 없음
    bad = make_criteria([], posting_id="88", suitable=False)            # 추출했지만 요건 없음
    bad.warnings = ["스냅샷에 본문 이미지가 없음"]
    save_criteria(criteria_dir(s.data_dir, "saramin", "88"), bad)
    assert [p["posting_id"] for p in c.get("/api/postings").json()] == ["55"]
    excluded = {e["posting_id"]: e for e in c.get("/api/excluded").json()}
    assert set(excluded) == {"77", "88"}
    assert "본문 이미지가 없음" in excluded["77"]["reason"] and "1722자" in excluded["77"]["reason"]
    assert excluded["77"]["url"] == "https://saramin/77"
    assert excluded["88"]["reason"] == "스냅샷에 본문 이미지가 없음"
    page = c.get("/excluded")
    assert page.status_code == 200 and "처리하지 않은 공고" in page.text
    assert "/excluded" not in c.get("/").text                         # 기본 화면에는 링크도 두지 않음


def test_cost_endpoint_and_page(tmp_path):
    c, s = client_for(tmp_path)
    assert c.get("/api/cost").json()["total"]["calls"] == 0                   # 호출 기록 없음
    c.post("/api/postings/55/match", json={"refresh": False})                 # 대역 LLM — 캐시 없음
    llm_dir = s.data_dir / "cache" / "llm"
    llm_dir.mkdir(parents=True, exist_ok=True)
    (llm_dir / "judge-55-a-1.json").write_text('{"tag": "judge-55-a", "model": "gpt-4.1", "response": {}, '
                                               '"usage": {"input_tokens": 1000, "output_tokens": 100}}')
    body = c.get("/api/cost").json()
    assert body["total"]["calls"] == 1 and abs(body["total"]["cost"] - 0.0028) < 1e-9
    [p] = body["postings"]
    assert (p["posting_id"], p["title"]) == ("55", "테스트 공고")
    page = c.get("/cost")
    assert page.status_code == 200 and "/api/cost" in page.text
    assert 'href="/cost"' in c.get("/").text                                  # 매칭 화면에서 들어갈 수 있다
