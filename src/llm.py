"""LLM 경계. 전처리·스코어링은 LLM 프로토콜에만 의존한다.

- OpenAILLM: 실제 OpenAI 호출
- CachedLLM: 다른 LLM을 감싸 응답을 디스크에 캐시 (ADR-0014)
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

MIME = {".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}


class LLM(Protocol):
    def vision_text(self, *, model: str, system: str, image: Path,
                    user_text: Optional[str] = None, tag: str = "") -> str: ...

    def structured(self, *, model: str, system: str, user: str, schema: type[T], tag: str = "") -> T: ...


def image_data_url(path: Path) -> str:
    mime = MIME.get(path.suffix.lower(), "image/jpeg")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


class OpenAILLM:
    def __init__(self, client=None):
        if client is None:
            from openai import OpenAI

            client = OpenAI()  # OPENAI_API_KEY 환경변수 사용
        self.client = client

    def vision_text(self, *, model: str, system: str, image: Path,
                    user_text: Optional[str] = None, tag: str = "") -> str:
        content: list[dict] = []
        if user_text:
            content.append({"type": "text", "text": user_text})
        content.append({"type": "image_url", "image_url": {"url": image_data_url(image), "detail": "high"}})
        resp = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
        )
        return resp.choices[0].message.content or ""

    def structured(self, *, model: str, system: str, user: str, schema: type[T], tag: str = "") -> T:
        resp = self.client.chat.completions.parse(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=schema,
        )
        msg = resp.choices[0].message
        if msg.parsed is None:
            raise RuntimeError(f"구조화 응답 실패: {msg.refusal}")
        return msg.parsed

    def list_models(self) -> list[str]:
        return sorted(m.id for m in self.client.models.list())


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class CachedLLM:
    """응답을 `{cache_dir}/{tag}-{hash16}.json`에 저장한다. 같은 입력이면 내부 LLM을 만들지도 부르지도 않는다."""

    def __init__(self, inner_factory: Callable[[], LLM], cache_dir: Path):
        self._factory = inner_factory
        self._inner: Optional[LLM] = None
        self.cache_dir = cache_dir

    @property
    def inner(self) -> LLM:
        if self._inner is None:
            self._inner = self._factory()
        return self._inner

    def vision_text(self, *, model: str, system: str, image: Path,
                    user_text: Optional[str] = None, tag: str = "") -> str:
        key = _hash({"kind": "vision", "model": model, "system": system, "user_text": user_text,
                     "image": hashlib.sha256(image.read_bytes()).hexdigest()})
        found, value = self._load(tag, key)
        if found:
            return value
        out = self.inner.vision_text(model=model, system=system, image=image, user_text=user_text, tag=tag)
        self._save(tag, key, model, out)
        return out

    def structured(self, *, model: str, system: str, user: str, schema: type[T], tag: str = "") -> T:
        key = _hash({"kind": "structured", "model": model, "system": system, "user": user,
                     "schema": schema.model_json_schema()})
        found, value = self._load(tag, key)
        if found:
            return schema.model_validate(value)
        out = self.inner.structured(model=model, system=system, user=user, schema=schema, tag=tag)
        self._save(tag, key, model, out.model_dump(mode="json"))
        return out

    def _path(self, tag: str, key: str) -> Path:
        safe = re.sub(r"[^\w.-]", "_", tag) or "call"
        return self.cache_dir / f"{safe}-{key[:16]}.json"

    def _load(self, tag: str, key: str) -> tuple[bool, Any]:
        path = self._path(tag, key)
        if not path.exists():
            return False, None
        return True, json.loads(path.read_text(encoding="utf-8"))["response"]

    def _save(self, tag: str, key: str, model: str, response: Any) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._path(tag, key).write_text(
            json.dumps({"tag": tag, "model": model, "response": response}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
