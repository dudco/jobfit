"""수집 서비스. CLI·API·UI가 공통으로 호출한다 (ADR-0002)."""
from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import httpx

from ..settings import Settings
from . import saramin
from .images import extension, inspect_image
from .snapshot import (
    SNAPSHOT_FILE, PostingSnapshot, SourceRef, StoredImage, load_snapshot, save_file, save_snapshot, snapshot_dir,
)

SITE = "saramin"
IMAGE_POSTING_MAX_TEXT = 300  # 본문 텍스트(공백 제외)가 이보다 길면 이미지형 공고로 보지 않는다

Log = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def make_client(settings: Settings) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": settings.user_agent}, follow_redirects=True, timeout=20)


def crawl(ref: str, settings: Settings, *, client: httpx.Client,
          refresh: bool = False, log: Log = _noop) -> PostingSnapshot:
    """공고 1건을 스냅샷으로 저장한다. 완전한 스냅샷이 있으면 네트워크 없이 재사용한다."""
    rec_idx = saramin.parse_rec_idx(ref)
    target = snapshot_dir(settings.data_dir, SITE, rec_idx)
    existing = load_snapshot(target)
    if existing is not None and not refresh:
        log(f"[crawl] 스냅샷 재사용: {target}")
        return existing

    view_url = saramin.VIEW_URL.format(rec_idx=rec_idx)
    referer = {"Referer": view_url}
    log(f"[crawl] 사람인 공고 {rec_idx} 수집")
    view = _get(client, settings, view_url)
    detail = _get(client, settings, saramin.DETAIL_URL.format(rec_idx=rec_idx), referer)

    # 이전 스냅샷 무효화: 매니페스트를 먼저 지워, 이후 실패해도 불완전한 스냅샷이 남지 않게
    (target / SNAPSHOT_FILE).unlink(missing_ok=True)
    shutil.rmtree(target / "images", ignore_errors=True)

    images: list[StoredImage] = []
    skipped: list[str] = []
    for url in saramin.extract_image_urls(detail.text):
        resp = _get(client, settings, url, referer)
        info = inspect_image(resp.content)
        if info is None:
            skipped.append(url)
            continue
        stored = save_file(target, f"images/{len(images):02d}{extension(info)}", resp.content)
        images.append(StoredImage(**stored.model_dump(), index=len(images), source_url=url,
                                  format=info.format, width=info.width, height=info.height))

    text_length = saramin.body_text_length(detail.text)
    snapshot = PostingSnapshot(
        source=SourceRef(site=SITE, posting_id=rec_idx, url=view_url),
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        title=saramin.extract_title(view.text),
        view_html=save_file(target, "view.html", view.content),
        detail_html=save_file(target, "detail.html", detail.content),
        images=images,
        skipped_images=skipped,
        body_text_length=text_length,
        is_image_posting=bool(images) and text_length <= IMAGE_POSTING_MAX_TEXT,
    )
    save_snapshot(target, snapshot)
    log(f"[crawl] 이미지 {len(images)}장 저장, 제외 {len(skipped)}건 → {target}")
    return snapshot


def _get(client: httpx.Client, settings: Settings, url: str,
         headers: Optional[dict] = None) -> httpx.Response:
    time.sleep(settings.request_interval)
    resp = client.get(url, headers=headers)
    resp.raise_for_status()
    return resp
