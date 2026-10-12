"""CLI 어댑터. 서비스 함수를 호출하고 결과를 출력만 한다 (ADR-0002)."""
from __future__ import annotations

import functools

from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

import pipeline
from flags import describe
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


def _friendly(fn):
    """서비스가 알려 주는 입력·데이터 문제(RuntimeError, ValueError)는 추적 정보 없이 메시지로 보여준다."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (RuntimeError, ValueError) as e:
            console.print(f"[red]{escape(str(e))}[/red]")
            raise typer.Exit(1)
    return wrapper


def _flag_legend(codes) -> None:
    """표에 나온 검증 표시의 뜻을 표 아래에 한 번씩 풀어 쓴다."""
    for code in dict.fromkeys(codes):
        info = describe(code)
        color = "yellow" if info.severity == "warning" else "dim"
        console.print(f"[{color}]⚑ {info.label}[/] — {info.explanation}")


def _log(msg: str) -> None:
    console.print(f"[dim]{msg}[/dim]")


@app.command()
@_friendly
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
@_friendly
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
        kind = ("필수" if r.priority == "must" else "우대") + (" (법정)" if r.sensitive else "")
        if r.flags:
            where += "".join(f"\n[{'yellow' if describe(f).severity == 'warning' else 'dim'}]⚑ {describe(f).label}[/]"
                             for f in r.flags)
        table.add_row(r.id, kind, r.category, r.text, ", ".join(r.positions) or "전체", where)
    console.print(table)
    if c.positions:
        console.print("모집분야: " + ", ".join(p.name for p in c.positions))
    cond = c.conditions
    parts = [x for x in [cond.employment_type, cond.schedule, *cond.locations, *cond.others] if x]
    if parts:
        console.print("근무조건(점수 미반영): " + " · ".join(parts))
    _flag_legend(f for r in c.requirements for f in r.flags)
    for warning in c.warnings:
        console.print(f"[yellow]⚠ {warning}[/yellow]")


@app.command("experiment-jev")
@_friendly
def experiment_jev(
    refs: List[str] = typer.Argument(..., help="rec_idx (기준 매칭 결과가 있어야 함)"),
    thresholds: str = typer.Option("0.5,0.6,0.7,0.8,0.9", "--thresholds", help="단계식 판정 확신도 기준"),
):
    """[실험] 판단 전용 모델(JEV) 판정을 기준(gpt-4.1)·목업 의도와 비교 (스펙 06). TYPESAFE_API_KEY 필요."""
    from scoring.experiment_jev import run_experiment
    from scoring.jev import CachedJev, real_client

    settings = load_settings()
    jev = CachedJev(real_client, settings.jev_cache_dir, model=settings.jev_model)
    ts = [float(x) for x in thresholds.split(",")]
    for ref in refs:
        r = run_experiment(parse_rec_idx(ref), settings, jev=jev, thresholds=ts, log=_log)
        console.rule(f"{r['posting_id']}  JEV {', '.join(r['jev_model'])}")
        console.print(f"판정 {r['judgments']}개 · 기준(gpt)과 일치 {r['agree_with_gpt']:.0%} · 점수 순위 상관 "
                      f"{r['spearman_vs_gpt']:.2f} · 근거 없는 판정 {r['jev']['no_evidence']} · "
                      f"확신도 중앙값 {r['confidence_median']:.2f}")
        for name in ("gpt", "jev"):
            e = r[name]
            console.print(f"  {name:>3}: 의도 순서 {'✓' if e['order_ok'] else '✗'} · 구간 이탈 {len(e['out_of_range'])} · "
                          f"의도 판정 일치 {e['expected'][0]}/{e['expected'][1]}")
        console.print(f"  JEV 비용 ${r['jev_cost_usd']:.5f} (입력 {r['input_tokens']:,} 토큰) · "
                      f"응답 중앙값 {r['latency_s_median']}s")
        table = Table("확신도 기준", "gpt로 넘김", "기준과 일치", "의도 판정 일치", "추정 비용")
        for c in r["cascade"]:
            table.add_row(f"{c['threshold']:.2f}", f"{c['escalated']}/{c['candidates']}명",
                          f"{c['agree_with_gpt']:.0%}", f"{c['expected_agreed']}/{c['expected_total']}",
                          f"${c['cost_usd']:.3f}")
        console.print(table)
        for dis in r["disagreements"][:12]:
            console.print(f"  [dim]{escape(dis['candidate'])} · {escape(dis['requirement'][:30])} — "
                          f"gpt {dis['gpt']} / jev {dis['jev']} ({dis['confidence']})[/dim]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="바인드 주소"),
    port: int = typer.Option(8000, "--port", help="포트"),
):
    """API와 UI를 띄운다 — 브라우저에서 http://{host}:{port} (API 문서: /docs)"""
    import uvicorn

    from api import create_app

    console.print(f"jobfit — http://{host}:{port}  (API 문서: /docs)")
    uvicorn.run(create_app(load_settings()), host=host, port=port)


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
        where = "전 분야 동일" if s.tied_positions else (s.position or "—")
        table.add_row(str(s.rank), str(s.score), escape(f"{s.candidate_id} {s.name}"), escape(where),
                      f"{best.must_met}/{best.must_total}", str(len(best.unknown)), labels.get(s.candidate_id, ""))
    console.print(table)
    for note in result.notes:
        console.print(f"[yellow]ℹ {escape(note)}[/yellow]")
    if any(label != "(타 공고)" for label in labels.values()):
        ev = evaluate_ranking(result, candidates)
        console.print(f"의도 순서 {'✓' if ev.order_ok else '✗'} · 구간 이탈 {len(ev.out_of_range)} · "
                      f"의도 판정 일치 {ev.agreed}/{ev.expected_total}")
        for line in ev.out_of_range + ev.disagreements:
            console.print(f"  [yellow]{escape(line)}[/yellow]")


@app.command("match")
@_friendly
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
@_friendly
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
        flag = "".join(f"\n[yellow]⚑ {describe(f).label}[/yellow]" for f in j.flags)
        table.add_row(escape(j.text), "필수" if j.priority == "must" else "우대", STATUS_TEXT[j.status] + rule + flag,
                      escape("\n".join(j.quotes)) or "—", escape(j.reason), f"{j.contribution:.1f}")
    console.print(table)
    _flag_legend(f for j in s.best.judgments for f in j.flags)
    for line in s.summary:
        console.print(f"· {escape(line)}")
    if s.excluded_sensitive:
        console.print("[dim]법정 우대 — 점수 미반영 (관계 법령·증빙에 따라 전형에서 별도 적용): "
                      + escape(", ".join(s.excluded_sensitive)) + "[/dim]")
