"""CLI 어댑터. 서비스 함수를 호출하고 결과를 출력만 한다 (ADR-0002)."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

import pipeline
from crawler.saramin import parse_rec_idx
from llm import CachedLLM, OpenAILLM, cached_openai
from preprocessing import service as preprocessing_service
from preprocessing.criteria import criteria_dir, load_criteria
from scoring import service as scoring_service
from scoring.candidate import load_candidates
from scoring.evaluate import evaluate_ranking
from scoring.result import load_result
from crawler import service
from crawler.snapshot import list_snapshots
from settings import ROOT, load_settings

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
    return cached_openai(settings.llm_cache_dir)


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


@app.command()
def evaluate(
    ref: str = typer.Argument(..., help="rec_idx 또는 URL"),
    truth: Optional[Path] = typer.Option(None, "--truth", help="정답 파일 (기본: tests/fixtures/criteria_truth/{rec_idx}.yaml)"),
):
    """추출 결과를 사람이 만든 정답 요건 목록과 비교 (스펙 02 실험)."""
    from preprocessing.evaluate import evaluate as run_evaluation, load_truth

    settings = load_settings()
    posting_id = parse_rec_idx(ref)
    c = load_criteria(criteria_dir(settings.data_dir, "saramin", posting_id))
    if c is None:
        console.print(f"[red]추출 결과가 없습니다 — 먼저 `jobfit extract {posting_id}`를 실행하세요[/red]")
        raise typer.Exit(1)
    truth_path = truth or ROOT / "tests" / "fixtures" / "criteria_truth" / f"{posting_id}.yaml"
    ev = run_evaluation(load_truth(truth_path), c)
    console.print(f"{posting_id}  재현율 {ev.recall:.0%}  정밀도 {ev.precision:.0%}  필수 재현율 {ev.must_recall:.0%}  "
                  f"필수/우대 일치 {ev.priority_agreement:.0%}  유형 일치 {ev.category_agreement:.0%}")
    for t in ev.missed:
        console.print(f"  누락: {t.text}")
    for r in ev.extra:
        console.print(f"  추가: {r.id} {r.text}")
    for t, r in ev.matched:
        if t.priority != r.priority or t.category != r.category:
            console.print(f"  불일치: {r.id} {r.text} — 정답 {t.priority}/{t.category}, 추출 {r.priority}/{r.category}")


# --- ③ 스코어링 (스펙 03) ---

STATUS_TEXT = {"met": "[green]충족[/green]", "partial": "[yellow]부분[/yellow]", "unmet": "[red]미충족[/red]",
               "unknown": "[cyan]확인 필요[/cyan]", "not_applicable": "[dim]해당 없음[/dim]"}


def _print_ranking(result, candidates) -> None:
    """랭킹 표. 의도 라벨은 목업 meta에서 표시만 한다 (점수 계산은 meta를 읽지 않음)."""
    posting_id = result.posting.posting_id
    labels = {c.id: (c.meta.label if c.meta and c.meta.target_posting == posting_id else "(타 공고)")
              for c in candidates}
    table = Table("순위", "점수", "지원자", "분야", "필수 충족", "확인 필요", "의도",
                  title=f"{escape(result.posting.title)} ({posting_id})")
    for s in result.candidates:
        best = s.best
        table.add_row(str(s.rank), str(s.score), escape(f"{s.candidate_id} {s.name}"), escape(s.position or "—"),
                      f"{best.must_met}/{best.must_total}", str(len(best.unknown)), labels.get(s.candidate_id, ""))
    console.print(table)
    if any(label != "(타 공고)" for label in labels.values()):
        ev = evaluate_ranking(result, candidates)
        console.print(f"의도 순서 {'✓' if ev.order_ok else '✗'} · 구간 이탈 {len(ev.out_of_range)} · "
                      f"의도 판정 일치 {ev.agreed}/{ev.expected_total}")
        for line in ev.out_of_range + ev.disagreements:
            console.print(f"  [yellow]{escape(line)}[/yellow]")


@app.command("match")
def match_cmd(
    refs: List[str] = typer.Argument(..., help="사람인 공고 URL 또는 rec_idx (여러 개 가능)"),
    candidates: Optional[Path] = typer.Option(None, "--candidates", help="지원자 JSON 디렉터리 (기본: 설정 candidates_dir)"),
    refresh: bool = typer.Option(False, "--refresh", help="기존 결과를 무시하고 다시 (판정은 캐시 사용)"),
):
    """지원자를 공고 조건으로 판정·점수화하고 랭킹을 data/results/에 저장."""
    settings = load_settings()
    llm = make_llm(settings)
    candidates = candidates or settings.candidates_dir
    people = load_candidates(candidates)
    for ref in refs:
        result = scoring_service.match(ref, settings, llm=llm, candidates_dir=candidates, refresh=refresh, log=_log)
        _print_ranking(result, people)


@app.command("run")
def run_cmd(
    refs: List[str] = typer.Argument(..., help="사람인 공고 URL 또는 rec_idx (여러 개 가능)"),
    refresh: bool = typer.Option(False, "--refresh", help="매칭만 다시 (수집·추출은 재사용)"),
):
    """수집 → 조건 추출 → 매칭을 한 번에 실행하고 랭킹을 보여준다."""
    settings = load_settings()
    llm = make_llm(settings)
    people = load_candidates(settings.candidates_dir)
    for ref in refs:
        result = pipeline.run(ref, settings, llm=llm, refresh=refresh, log=_log)
        _print_ranking(result, people)


@app.command()
def result(
    ref: str = typer.Argument(..., help="rec_idx 또는 URL"),
    candidate: Optional[str] = typer.Option(None, "--candidate", help="지원자 id — 요건별 판정·근거·기여 점수"),
    candidates: Optional[Path] = typer.Option(None, "--candidates", help="지원자 JSON 디렉터리 (의도 라벨 표시용)"),
):
    """저장된 매칭 결과. --candidate로 요건별 근거를 본다."""
    settings = load_settings()
    posting_id = parse_rec_idx(ref)
    res = load_result(settings.data_dir, "saramin", posting_id)
    if res is None:
        console.print(f"[red]매칭 결과가 없습니다 — 먼저 `jobfit match {posting_id}`를 실행하세요[/red]")
        raise typer.Exit(1)
    if candidate is None:
        _print_ranking(res, load_candidates(candidates or settings.candidates_dir))
        return
    s = next((x for x in res.candidates if x.candidate_id == candidate), None)
    if s is None:
        console.print(f"[red]지원자 {escape(candidate)} 없음[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{s.rank}위 {escape(s.candidate_id)} {escape(s.name)} — {s.score}점[/bold]  "
                  f"분야: {escape(s.position or '—')}")
    if len(s.positions) > 1:
        console.print("분야별: " + ", ".join(f"{escape(p.position or '—')} {p.score}" for p in s.positions))
    table = Table("요건", "구분", "판정", "근거 (이력서)", "사유", "기여")
    for j in s.best.judgments:
        rule = f" [dim]({j.rule})[/dim]" if j.rule else ""
        flag = f" [red]⚑ {escape(', '.join(j.flags))}[/red]" if j.flags else ""
        table.add_row(escape(j.text), "필수" if j.priority == "must" else "우대", STATUS_TEXT[j.status] + rule + flag,
                      escape("\n".join(j.quotes)) or "—", escape(j.reason), f"{j.contribution:.1f}")
    console.print(table)
    for line in s.summary:
        console.print(f"· {escape(line)}")
    if s.excluded_sensitive:
        console.print("[dim]법정 우대 — 점수 미반영 (관계 법령·증빙에 따라 전형에서 별도 적용): "
                      + escape(", ".join(s.excluded_sensitive)) + "[/dim]")
