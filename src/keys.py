"""API 키 확인 — 키가 없으면 작업을 시작하기 전에 이유와 함께 멈춘다."""
from __future__ import annotations

import os

KEYS = {
    "OPENAI_API_KEY": "OpenAI (조건 추출·지원자 판정)",
    "TYPESAFE_API_KEY": "TypeSafe JEV (판단 전용 모델 실험)",
}


class MissingApiKeyError(RuntimeError):
    pass


def require_api_key(name: str) -> None:
    """환경변수(.env 포함)에 키가 없으면 MissingApiKeyError. load_settings()로 .env를 읽은 뒤 부른다."""
    if not os.environ.get(name, "").strip():
        raise MissingApiKeyError(
            f"{name}가 설정되지 않음 — {KEYS.get(name, name)}에 필요합니다. "
            f"레포 루트 .env에 `{name}=…`를 추가하세요 (.env는 커밋되지 않음)")
