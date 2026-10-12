"""CLI 어댑터. 서비스 함수를 호출하고 결과를 출력만 한다 (ADR-0002)."""
from __future__ import annotations

from typing import List

import typer
from rich.console import Console
from rich.table import Table

from crawler.saramin import parse_rec_idx
from llm import CachedLLM, OpenAILLM
from preprocessing import service as preprocessing_service
from preprocessing.criteria import criteria_dir, load_criteria
from crawler import service
from crawler.snapshot import list_snapshots
from settings import load_settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="이미지 채용공고 수집·구조화·매칭")
console = Console()


def _log(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")


@app.command()
def crawl(
    refs: List[str] = typer.Argument(..., help="사람인 공고 URL 또는 rec_idx (여러 개 가능)"),
    refresh: bool = typer.Option(False, "--refresh", help="기존 스냅샷을 무시하고 다시 수집"),
):
    """공고 원본(HTML·본문 이미지)을 data/postings/에 스냅샷으로 저장."""
    settings = load_settings()
    with service.make_client(settings) as client:
        for ref in refs:
            snap = service.crawl(ref, settings, client=client, refresh=refresh, log=_log)
            kind = "이미지 공고" if snap.is_image_posting else "[yellow]이미지 공고 아님?[/yellow]"
            console.print(f"{snap.source.posting_id}  이미지 {len(snap.images)}장  {kind}  {snap.title or ''}")


@app.command()
def postings():
    """저장된 공고 스냅샷 목록."""
    settings = load_settings()
    table = Table("사이트", "ID", "이미지", "이미지 공고", "수집 시각", "제목")
    for s in list_snapshots(settings.data_dir):
        table.add_row(s.source.site, s.source.posting_id, str(len(s.images)),
                      "예" if s.is_image_posting else "아니오", s.fetched_at, s.title or "")
    console.print(table)


def make_llm(settings) -> CachedLLM:
    """응답 캐시(ADR-0014)를 거치는 OpenAI 클라이언트. 캐시 적중이면 API 키가 없어도 된다."""
    return CachedLLM(OpenAILLM, settings.llm_cache_dir)


@app.command()
def extract(
    refs: List[str] = typer.Argument(..., help="사람인 공고 URL 또는 rec_idx (여러 개 가능)"),
    refresh: bool = typer.Option(False, "--refresh", help="기존 추출 결과를 무시하고 다시 추출"),
):
    """공고 스냅샷의 이미지에서 조건을 추출해 data/criteria/에 저장."""
    settings = load_settings()
    llm = make_llm(settings)
    for ref in refs:
        c = preprocessing_service.extract(ref, settings, llm=llm, refresh=refresh, log=_log)
        must = sum(r.priority == "must" for r in c.requirements)
        status = "" if c.suitable else "  [red]부적합[/red]"
        console.print(f"{c.source.posting_id}  요건 {len(c.requirements)}개 (필수 {must}, "
                      f"우대 {len(c.requirements) - must})  모집분야 {len(c.positions)}  "
                      f"⚠ {len(c.warnings)}  {c.title}{status}")


@app.command()
def criteria(ref: str = typer.Argument(..., help="rec_idx 또는 URL")):
    """추출된 공고 조건을 표로 보여준다."""
    settings = load_settings()
    posting_id = parse_rec_idx(ref)
    c = load_criteria(criteria_dir(settings.data_dir, "saramin", posting_id))
    if c is None:
        console.print(f"[red]추출 결과가 없습니다 — 먼저 `jobfit extract {posting_id}`를 실행하세요[/red]")
        raise typer.Exit(1)
    console.rule(f"{c.title} ({c.job_family})")
    table = Table("id", "구분", "유형", "요건", "모집분야", "근거")
    for r in c.requirements:
        where = (f"img{r.evidence.image_index}/slice{r.evidence.slice_index}"
                 if r.evidence.slice_index is not None else "✗ 없음")
        kind = ("필수" if r.priority == "must" else "우대") + (" ⚑" if r.sensitive else "")
        table.add_row(r.id, kind, r.category, r.text, ", ".join(r.positions) or "전체", where)
    console.print(table)
    if c.positions:
        console.print("모집분야: " + ", ".join(p.name for p in c.positions))
    cond = c.conditions
    parts = [x for x in [cond.employment_type, cond.schedule, *cond.locations, *cond.others] if x]
    if parts:
        console.print("근무조건(점수 미반영): " + " · ".join(parts))
    for warning in c.warnings:
        console.print(f"[yellow]⚠ {warning}[/yellow]")


@app.command()
def models():
    """현재 API 키로 사용 가능한 모델 목록 (OPENAI_API_KEY 필요)."""
    load_settings()  # .env 로드
    for name in OpenAILLM().list_models():
        console.print(name)
