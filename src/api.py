"""HTTP 어댑터 (ADR-0002, 0019). 서비스 함수 호출과 오류 변환만 한다.

응답은 저장 파일과 같은 pydantic 모델(PostingCriteria, MatchResult)이다. UI(web/index.html)는 이 API만 쓴다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx
import openai
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import pipeline
from flags import FLAGS
from crawler.saramin import parse_rec_idx
from crawler.service import SITE
from crawler.snapshot import list_snapshots
from keys import require_api_key
from llm import LLM, cached_openai
from preprocessing.criteria import PostingCriteria, criteria_dir, list_criteria, load_criteria
from scoring import service as scoring_service
from scoring.candidate import load_candidates, render_lines
from scoring.result import MatchResult, Weights, load_result
from settings import Settings, load_settings

WEB_DIR = Path(__file__).resolve().parent / "web"


class PostingSummary(BaseModel):
    posting_id: str
    title: str
    company: Optional[str]
    job_family: str
    requirements: int
    must: int
    preferred: int
    positions: int
    suitable: bool
    matched_at: Optional[str]


class CandidateView(BaseModel):
    id: str
    name: str
    headline: str
    lines: list[str]                  # render_lines() — 판정 LLM이 본 그대로 (줄 번호 = 인덱스 + 1)
    target_posting: Optional[str]     # 평가용 (meta)
    label: Optional[str]              # 평가용 (meta)


class ExcludedPosting(BaseModel):
    """처리하지 않은(평가할 수 없는) 공고 — 기본 화면에서 숨기고 /excluded에서만 보인다."""
    posting_id: str
    title: Optional[str]
    url: Optional[str]
    reason: str
    fetched_at: Optional[str]


class MatchRequest(BaseModel):
    refresh: bool = False


class RunRequest(BaseModel):
    ref: str
    refresh: bool = False


def _quiet(_msg: str) -> None:
    pass


def create_app(settings: Optional[Settings] = None, llm: Optional[LLM] = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="jobfit", description="이미지 채용공고 수집·구조화·지원자 매칭 API")
    holder: list[LLM] = [llm] if llm is not None else []

    def get_llm() -> LLM:
        if not holder:
            require_api_key("OPENAI_API_KEY")           # 없으면 400 — 작업 전에 알린다
            holder.append(cached_openai(settings.llm_cache_dir))
        return holder[0]

    def criteria_or_404(posting_id: str) -> PostingCriteria:
        c = load_criteria(criteria_dir(settings.data_dir, SITE, posting_id))
        if c is None:
            raise HTTPException(404, f"공고 {posting_id}의 조건이 없음 — 먼저 실행")
        return c

    def result_or_404(posting_id: str) -> MatchResult:
        res = load_result(settings.data_dir, SITE, posting_id)
        if res is None:
            raise HTTPException(404, f"공고 {posting_id}의 매칭 결과가 없음 — 먼저 실행")
        return res

    async def bad_request(_: Request, exc: Exception):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    async def upstream(_: Request, exc: Exception):
        return JSONResponse(status_code=502, content={"detail": f"외부 요청 실패: {exc}"})

    app.add_exception_handler(RuntimeError, bad_request)
    app.add_exception_handler(ValueError, bad_request)
    app.add_exception_handler(httpx.HTTPError, upstream)
    app.add_exception_handler(openai.APIError, upstream)

    @app.get("/api/postings", response_model=list[PostingSummary])
    def postings():
        out = []
        for c in list_criteria(settings.data_dir):
            if not c.suitable:                     # 평가할 수 없는 공고는 /api/excluded로
                continue
            res = load_result(settings.data_dir, SITE, c.source.posting_id)
            must = sum(r.priority == "must" for r in c.requirements)
            out.append(PostingSummary(
                posting_id=c.source.posting_id, title=c.title, company=c.company, job_family=c.job_family,
                requirements=len(c.requirements), must=must, preferred=len(c.requirements) - must,
                positions=len(c.positions), suitable=c.suitable, matched_at=res.matched_at if res else None))
        return out

    @app.get("/api/excluded", response_model=list[ExcludedPosting])
    def excluded():
        """본문 이미지가 없거나(텍스트 공고) 요건을 추출하지 못한 공고와 그 이유."""
        criteria_by_id = {c.source.posting_id: c for c in list_criteria(settings.data_dir)}
        out, seen = [], set()
        for snap in list_snapshots(settings.data_dir):
            pid, c = snap.source.posting_id, criteria_by_id.get(snap.source.posting_id)
            if not snap.images:
                reason = (f"본문 이미지가 없음 (본문 텍스트 {snap.body_text_length}자) — "
                          "조건은 공고 이미지에서만 추출하므로 처리하지 않음")
            elif c is not None and not c.suitable:
                reason = "; ".join(c.warnings) or "추출된 요건 없음"
            else:
                continue                            # 정상 공고 또는 아직 추출 전
            seen.add(pid)
            out.append(ExcludedPosting(posting_id=pid, title=snap.title, url=snap.source.url, reason=reason,
                                       fetched_at=snap.fetched_at))
        for pid, c in criteria_by_id.items():       # 스냅샷 없이 조건만 남은 경우
            if not c.suitable and pid not in seen:
                out.append(ExcludedPosting(posting_id=pid, title=c.title or None, url=None,
                                           reason="; ".join(c.warnings) or "추출된 요건 없음", fetched_at=None))
        return out

    @app.get("/api/cost")
    def cost():
        """지금까지 쓴 API 토큰·비용 — 캐시 파일 기준 (캐시 적중은 무료). 단계별·공고별 합계와 가격표."""
        from usage import report

        titles = {snap.source.posting_id: snap.title for snap in list_snapshots(settings.data_dir)}
        titles.update({c.source.posting_id: c.title for c in list_criteria(settings.data_dir) if c.title})
        return report(settings.data_dir, titles)

    @app.get("/cost", include_in_schema=False)
    def cost_page():
        return FileResponse(WEB_DIR / "cost.html", media_type="text/html")

    @app.get("/excluded", include_in_schema=False)
    def excluded_page():
        return FileResponse(WEB_DIR / "excluded.html", media_type="text/html")

    @app.get("/api/postings/{posting_id}/criteria", response_model=PostingCriteria)
    def criteria(posting_id: str):
        return criteria_or_404(posting_id)

    @app.get("/api/postings/{posting_id}/slices/{n}")
    def slice_image(posting_id: str, n: int):
        """근거 위치의 공고 조각. n = 전사의 조각 일련번호 = 조각 파일 이름 정렬 순서."""
        files = sorted((criteria_dir(settings.data_dir, SITE, posting_id) / "slices").glob("*.png"))
        if not 0 <= n < len(files):
            raise HTTPException(404, "조각 없음")
        return FileResponse(files[n], media_type="image/png")

    @app.get("/api/postings/{posting_id}/result", response_model=MatchResult)
    def result(posting_id: str):
        return result_or_404(posting_id)

    @app.post("/api/postings/{posting_id}/match", response_model=MatchResult)
    def match(posting_id: str, body: Optional[MatchRequest] = None):
        return scoring_service.match(posting_id, settings, llm=get_llm(), candidates_dir=settings.candidates_dir,
                                     refresh=(body or MatchRequest()).refresh, log=_quiet)

    @app.post("/api/postings/{posting_id}/rescore", response_model=MatchResult)
    def rescore(posting_id: str, weights: Weights):
        """가중치만 바꿔 재집계 — LLM 호출 없음, 저장하지 않음."""
        return scoring_service.rescore(result_or_404(posting_id), weights)

    @app.post("/api/run", response_model=MatchResult)
    def run(body: RunRequest):
        parse_rec_idx(body.ref)                              # 잘못된 입력은 네트워크 전에 400
        return pipeline.run(body.ref, settings, llm=get_llm(), refresh=body.refresh, log=_quiet)

    @app.get("/api/candidates", response_model=list[CandidateView])
    def candidates():
        return [CandidateView(id=c.id, name=c.name, headline=c.headline, lines=render_lines(c),
                              target_posting=c.meta.target_posting if c.meta else None,
                              label=c.meta.label if c.meta else None)
                for c in load_candidates(settings.candidates_dir)]

    @app.get("/api/flags")
    def flags():
        """검증 표시 코드의 뜻 (UI 설명용)."""
        return {code: {"label": f.label, "explanation": f.explanation, "severity": f.severity}
                for code, f in FLAGS.items()}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html", media_type="text/html")

    return app
