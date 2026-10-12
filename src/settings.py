"""실행 설정 (환경변수 / .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]  # 레포 루트 (src/의 부모)
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
DEFAULT_VISION_MODEL = "gpt-4.1"      # 스펙 02 실험 X2로 확정 (ADR-0010)
DEFAULT_TEXT_MODEL = "gpt-4.1"   # 스펙 02 실험 X2: mini는 유의사항의 우대 문구를 놓침
DEFAULT_JUDGE_MODEL = "gpt-4.1"  # 지원자 판정 (스펙 03)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    user_agent: str = DEFAULT_UA
    request_interval: float = 1.5      # 초. 사람인 요청마다 이만큼 쉰다
    vision_model: str = DEFAULT_VISION_MODEL
    text_model: str = DEFAULT_TEXT_MODEL
    slice_height: int = 1200           # 분할 목표 높이. 0 = 분할하지 않음 (ADR-0012)
    max_width: int = 1000              # 이보다 넓은 이미지는 비율 유지 축소
    judge_model: str = DEFAULT_JUDGE_MODEL

    @property
    def llm_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "llm"


def load_settings(*, dotenv_path: Optional[Path] = ROOT / ".env") -> Settings:
    """환경변수에서 설정을 읽는다. dotenv_path=None이면 .env를 읽지 않는다 (테스트용)."""
    if dotenv_path is not None:
        load_dotenv(dotenv_path)
    env = os.environ.get
    return Settings(
        data_dir=Path(env("JOBFIT_DATA_DIR", str(ROOT / "data"))),
        request_interval=float(env("JOBFIT_REQUEST_INTERVAL", "1.5")),
        vision_model=env("JOBFIT_VISION_MODEL", DEFAULT_VISION_MODEL),
        text_model=env("JOBFIT_TEXT_MODEL", DEFAULT_TEXT_MODEL),
        slice_height=int(env("JOBFIT_SLICE_HEIGHT", "1200")),
        max_width=int(env("JOBFIT_MAX_WIDTH", "1000")),
        judge_model=env("JOBFIT_JUDGE_MODEL", DEFAULT_JUDGE_MODEL),
    )
