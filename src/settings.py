"""실행 설정 (환경변수 / .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]  # 레포 루트 (src/의 부모)
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    user_agent: str = DEFAULT_UA
    request_interval: float = 1.5  # 초. 요청마다 이만큼 쉰다


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    return Settings(
        data_dir=Path(os.environ.get("JOBFIT_DATA_DIR", ROOT / "data")),
        request_interval=float(os.environ.get("JOBFIT_REQUEST_INTERVAL", "1.5")),
    )
