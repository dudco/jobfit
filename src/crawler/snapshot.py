"""수집 단계 산출물: 공고 원본 스냅샷과 매니페스트 (ADR-0005).

다음 단계(전처리)는 사람인이 아니라 이 매니페스트만 입력으로 받는다.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

SNAPSHOT_FILE = "snapshot.json"


class SourceRef(BaseModel):
    site: str                                   # "saramin"
    method: Literal["crawl", "upload"] = "crawl"  # upload: 운영 시 고객사 경유 유입 (자리만)
    posting_id: str                             # 사람인 rec_idx
    url: str                                    # 사람이 보는 공고 페이지


class StoredFile(BaseModel):
    path: str      # 스냅샷 디렉터리 기준 상대경로
    sha256: str
    bytes: int


class StoredImage(StoredFile):
    index: int     # 본문 내 순서 (저장된 이미지 기준 0부터)
    source_url: str
    format: str
    width: int
    height: int


class PostingSnapshot(BaseModel):
    schema_version: int = 1
    source: SourceRef
    fetched_at: str
    title: Optional[str] = None                 # 식별용 메타데이터 — 매칭 조건으로 쓰지 않음
    view_html: Optional[StoredFile] = None
    detail_html: StoredFile
    images: list[StoredImage] = Field(default_factory=list)
    skipped_images: list[str] = Field(default_factory=list)
    body_text_length: int
    is_image_posting: bool


def snapshot_dir(data_dir: Path, site: str, posting_id: str) -> Path:
    return data_dir / "postings" / site / posting_id


def save_file(directory: Path, rel_path: str, data: bytes) -> StoredFile:
    """원본 바이트를 그대로 저장하고 해시·크기를 돌려준다."""
    path = directory / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return StoredFile(path=rel_path, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


def save_snapshot(directory: Path, snapshot: PostingSnapshot) -> Path:
    """매니페스트는 마지막에, 원자적으로 쓴다 — 매니페스트가 있으면 완전한 스냅샷이다."""
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / SNAPSHOT_FILE
    tmp = final.with_suffix(".json.tmp")
    tmp.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, final)
    return final


def load_snapshot(directory: Path) -> Optional[PostingSnapshot]:
    path = directory / SNAPSHOT_FILE
    if not path.exists():
        return None
    return PostingSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def list_snapshots(data_dir: Path) -> list[PostingSnapshot]:
    paths = sorted((data_dir / "postings").glob(f"*/*/{SNAPSHOT_FILE}"))
    return [PostingSnapshot.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]
