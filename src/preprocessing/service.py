"""전처리 서비스. CLI·API가 공통으로 호출한다 (ADR-0002).

입력은 공고 스냅샷의 **이미지뿐**이다. HTML(view.html, detail.html)은 읽지 않는다 (ADR-0008).
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from PIL import Image

from crawler.saramin import parse_rec_idx
from crawler.service import SITE
from crawler.snapshot import PostingSnapshot, load_snapshot, snapshot_dir
from llm import LLM
from settings import Settings

from .criteria import CRITERIA_FILE, CriteriaSource, PostingCriteria, criteria_dir, load_criteria, save_criteria
from .images import slice_image
from .structure import structure
from .transcribe import SliceRef, transcribe
from .verify import build_criteria

TRANSCRIPT_FILE = "transcript.md"

Log = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def prepare_slices(snapshot: PostingSnapshot, snap_dir: Path, out_dir: Path, settings: Settings) -> list[SliceRef]:
    """스냅샷 이미지 → 정규화·분할한 조각 PNG (out_dir/slices/{이미지}_{조각}.png)."""
    slices_dir = out_dir / "slices"
    shutil.rmtree(slices_dir, ignore_errors=True)
    slices_dir.mkdir(parents=True)
    refs: list[SliceRef] = []
    for image in snapshot.images:
        with Image.open(snap_dir / image.path) as im:
            pieces = slice_image(im, max_width=settings.max_width, target_height=settings.slice_height)
        for part, piece in enumerate(pieces):
            path = slices_dir / f"{image.index:02d}_{part:02d}.png"
            piece.save(path)
            refs.append(SliceRef(path=path, image_index=image.index, part=part))
    return refs


def extract(ref: str, settings: Settings, *, llm: LLM, refresh: bool = False, log: Log = _noop) -> PostingCriteria:
    """공고 1건의 조건을 추출해 data/criteria/{site}/{id}/에 저장한다. 결과가 있으면 재사용한다."""
    posting_id = parse_rec_idx(ref)
    snap_dir = snapshot_dir(settings.data_dir, SITE, posting_id)
    snapshot = load_snapshot(snap_dir)
    if snapshot is None:
        raise RuntimeError(f"공고 스냅샷이 없습니다 — 먼저 `jobfit crawl {posting_id}`를 실행하세요")

    out_dir = criteria_dir(settings.data_dir, SITE, posting_id)
    existing = load_criteria(out_dir)
    if existing is not None and not refresh:
        log(f"[extract] 기존 결과 재사용: {out_dir}")
        return existing
    (out_dir / CRITERIA_FILE).unlink(missing_ok=True)   # 실패하면 결과가 남지 않게 먼저 지운다

    source = CriteriaSource(site=SITE, posting_id=posting_id, snapshot_fetched_at=snapshot.fetched_at,
                            image_sha256=[i.sha256 for i in snapshot.images])
    models = {"transcribe": settings.vision_model, "structure": settings.text_model}
    extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not snapshot.images:
        criteria = PostingCriteria(source=source, extracted_at=extracted_at, models=models, title="",
                                   job_family="", suitable=False, warnings=["스냅샷에 본문 이미지가 없음"])
    else:
        slices = prepare_slices(snapshot, snap_dir, out_dir, settings)
        log(f"[extract] 공고 {posting_id}: 이미지 {len(snapshot.images)}장 → 조각 {len(slices)}개 전사")
        transcript = transcribe(llm, slices, model=settings.vision_model, posting_id=posting_id)
        (out_dir / TRANSCRIPT_FILE).write_text(transcript, encoding="utf-8")
        log(f"[extract] 구조화 ({settings.text_model})")
        structured = structure(llm, transcript, model=settings.text_model, posting_id=posting_id)
        criteria = build_criteria(structured, transcript, source=source, models=models, extracted_at=extracted_at)

    save_criteria(out_dir, criteria)
    for warning in criteria.warnings:
        log(f"[extract] 경고: {warning}")
    return criteria
