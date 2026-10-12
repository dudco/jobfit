"""CLI 어댑터. 서비스 함수를 호출하고 결과를 출력만 한다 (ADR-0002)."""
from __future__ import annotations

from typing import List

import typer
from rich.console import Console
from rich.table import Table

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
