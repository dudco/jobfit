"""한 번에 실행: 수집 → 조건 추출 → 매칭 (ADR-0021). CLI `run`과 API `POST /api/run`이 호출한다.

각 단계는 산출물이 있으면 재사용한다. refresh는 매칭만 다시 한다 — 마감된 공고의 원본 스냅샷을 덮어쓰지 않게.
"""
from __future__ import annotations

from typing import Callable

from crawler import service as crawler_service
from crawler.saramin import parse_rec_idx
from llm import LLM
from preprocessing import service as preprocessing_service
from scoring import service as scoring_service
from scoring.result import MatchResult
from settings import Settings


def run(ref: str, settings: Settings, *, llm: LLM, client=None, refresh: bool = False,
        log: Callable[[str], None] = print) -> MatchResult:
    own = client is None
    client = client or crawler_service.make_client(settings)
    try:
        snapshot = crawler_service.crawl(ref, settings, client=client, log=log)
    finally:
        if own:
            client.close()
    if not snapshot.images:                  # 조건은 이미지에서만 얻는다 (ADR-0008) — 추출·매칭으로 넘기지 않는다
        raise RuntimeError(
            f"공고 {parse_rec_idx(ref)}은(는) 이미지 공고가 아님 — 본문이 텍스트({snapshot.body_text_length}자)이고 "
            "본문 이미지가 없음. 이 서비스는 공고 이미지에서만 조건을 추출합니다")
    preprocessing_service.extract(ref, settings, llm=llm, log=log)
    return scoring_service.match(ref, settings, llm=llm, candidates_dir=settings.candidates_dir,
                                 refresh=refresh, log=log)
