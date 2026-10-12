"""API 사용량·비용 집계 (`jobfit cost`).

응답 캐시 파일 하나 = 실제 API 호출 하나다 (캐시 적중은 호출하지 않으므로 파일이 생기지 않는다).
- 실측: 캐시 파일에 기록된 사용량 (OpenAI는 사용량 기록 기능 추가 이후, JEV는 처음부터)
- 추정: 사용량 기록 이전의 OpenAI 호출 — 현재 남아 있는 프롬프트 재료(조각 이미지 크기, 전사, 이력서)로 다시 세어 본 값
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# USD / 100만 토큰: (입력, 캐시된 입력, 출력). 공개 가격 기준 — 바뀌면 여기만 고친다.
PRICES_AS_OF = "2026-10"
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "jev": (0.042, 0.042, 0.0),
}
STAGES = {"transcribe": "전사(비전)", "structure": "구조화", "judge": "판정"}
SCHEMA_OVERHEAD = 400            # Structured Output 스키마·메시지 틀 (추정)


@dataclass
class UsageRow:
    basis: str                   # 실측 | 추정
    model: str
    stage: str
    calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


def price_for(model: str) -> tuple[float, float, float]:
    if model.startswith("jev"):
        return PRICES["jev"]
    for name in sorted(PRICES, key=len, reverse=True):     # gpt-4.1-mini가 gpt-4.1보다 먼저
        if model.startswith(name):
            return PRICES[name]
    return PRICES["gpt-4.1"]


def cost_of(model: str, input_tokens: int, cached: int, output: int) -> float:
    p_in, p_cached, p_out = price_for(model)
    return ((input_tokens - cached) * p_in + cached * p_cached + output * p_out) / 1_000_000


def estimate_tokens(text: str) -> int:
    """대략적인 토큰 수: ASCII 4자 ≈ 1토큰, 한글 등 1.5자 ≈ 1토큰."""
    ascii_chars = sum(c.isascii() for c in text)
    return round(ascii_chars / 4 + (len(text) - ascii_chars) / 1.5)


def _tiles(width: int, height: int) -> int:
    scale = min(1.0, 2048 / max(width, height))                # 2048×2048 안에 맞춤
    w, h = width * scale, height * scale
    scale = min(1.0, 768 / min(w, h))                          # 짧은 변 768
    w, h = w * scale, h * scale
    return math.ceil(w / 512) * math.ceil(h / 512)


def image_tokens(width: int, height: int) -> int:
    """gpt-4.1 계열 high detail 이미지 입력 토큰 (85 + 512px 조각당 170)."""
    return 85 + 170 * _tiles(width, height)


image_tokens.tiles = _tiles


def _estimate_input(tag: str, data_dir: Path) -> Optional[int]:
    """사용량 기록 이전 호출의 입력 토큰을 남아 있는 재료로 다시 센다. 재료가 없으면 None."""
    from crawler.service import SITE
    from preprocessing.criteria import criteria_dir, load_criteria
    from preprocessing.prompts import STRUCTURE_SYSTEM, TRANSCRIBE_SYSTEM

    parts = tag.split("-")
    stage, posting_id = parts[0], parts[1] if len(parts) > 1 else ""
    cdir = criteria_dir(data_dir, SITE, posting_id)
    if stage == "transcribe" and len(parts) > 2:
        slices = sorted((cdir / "slices").glob("*.png"))
        n = int(parts[2])
        if n >= len(slices):
            return None
        from PIL import Image
        with Image.open(slices[n]) as im:
            return image_tokens(*im.size) + estimate_tokens(TRANSCRIBE_SYSTEM) + 60
    if stage == "structure":
        transcript = cdir / "transcript.md"
        if not transcript.exists():
            return None
        return estimate_tokens(STRUCTURE_SYSTEM) + estimate_tokens(transcript.read_text(encoding="utf-8")) \
            + SCHEMA_OVERHEAD
    if stage == "judge" and len(parts) > 2:
        from scoring.candidate import load_candidates
        from scoring.judge import JUDGE_SYSTEM, build_prompt
        from scoring.service import applicable, derived_requirements, target_positions
        from settings import load_settings

        criteria = load_criteria(cdir)
        cid = "-".join(parts[2:])
        try:
            cand = next(c for c in load_candidates(load_settings().candidates_dir) if c.id == cid)
        except (StopIteration, ValueError):
            return None
        if criteria is None:
            return None
        positions = target_positions(criteria, cand)
        extra = derived_requirements(criteria)
        reqs = list({r.id: r for p in positions for r in applicable(criteria, p, extra)}.values())
        named = [p for p in positions if p] or None
        return estimate_tokens(JUDGE_SYSTEM + build_prompt(criteria, reqs, cand, named)) + SCHEMA_OVERHEAD
    return None


@dataclass
class Call:
    basis: str
    model: str
    stage: str
    posting_id: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int

    @property
    def cost(self) -> float:
        return cost_of(self.model, self.input_tokens, self.cached_input_tokens, self.output_tokens)


def calls(data_dir: Path) -> list[Call]:
    """캐시 파일마다 호출 하나. 사용량이 없으면 재료로 추정, 재료도 없으면 같은 단계 추정치의 중앙값."""
    out: list[Call] = []
    pending: list[tuple[str, str, str, int]] = []              # (모델, 단계, 공고, 출력 토큰)
    for path in sorted((data_dir / "cache" / "llm").glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        tag, model = rec.get("tag", path.stem), rec.get("model", "gpt-4.1")
        parts = tag.split("-")
        stage, posting_id = STAGES.get(parts[0], "기타"), parts[1] if len(parts) > 1 else ""
        usage = rec.get("usage")
        if usage:
            out.append(Call("실측", model, stage, posting_id, usage.get("input_tokens") or 0,
                            usage.get("cached_input_tokens") or 0, usage.get("output_tokens") or 0))
            continue
        response = rec.get("response")
        out_tokens = estimate_tokens(response if isinstance(response, str)
                                     else json.dumps(response, ensure_ascii=False))
        inp = _estimate_input(tag, data_dir)
        if inp is None:
            pending.append((model, stage, posting_id, out_tokens))
        else:
            out.append(Call("추정", model, stage, posting_id, inp, 0, out_tokens))
    for model, stage, posting_id, out_tokens in pending:
        same = [c.input_tokens for c in out if c.basis == "추정" and c.stage == stage]
        out.append(Call("추정", model, stage, posting_id, round(statistics.median(same)) if same else 1500, 0,
                        out_tokens))
    for path in sorted((data_dir / "cache" / "jev").glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        usage = rec.get("usage") or {}
        out.append(Call("실측", rec.get("model", "jev"), "판정(JEV)", path.stem.split("-")[0],
                        usage.get("input_tokens") or 0, 0, usage.get("output_tokens") or 0))
    return out


def _add(row, c: Call) -> None:
    row.calls += 1
    row.input_tokens += c.input_tokens
    row.cached_input_tokens += c.cached_input_tokens
    row.output_tokens += c.output_tokens
    row.cost += c.cost


def summarize(data_dir: Path, records: Optional[list[Call]] = None) -> list[UsageRow]:
    """구분(실측·추정) × 모델 × 단계별 합계."""
    rows: dict[tuple[str, str, str], UsageRow] = {}
    for c in calls(data_dir) if records is None else records:
        _add(rows.setdefault((c.basis, c.model, c.stage), UsageRow(c.basis, c.model, c.stage)), c)
    return sorted(rows.values(), key=lambda r: (r.basis, r.model, r.stage))


def report(data_dir: Path, titles: Optional[dict[str, str]] = None) -> dict:
    """화면·API용: 단계별 행, 공고별 합계(비용 큰 순), 전체 합계, 가격표."""
    records = calls(data_dir)
    rows = summarize(data_dir, records)
    postings: dict[str, dict] = {}
    for c in records:
        p = postings.setdefault(c.posting_id, {"posting_id": c.posting_id, "title": (titles or {}).get(c.posting_id),
                                               "calls": 0, "cost": 0.0, "stages": {}})
        p["calls"] += 1
        p["cost"] += c.cost
        p["stages"][c.stage] = p["stages"].get(c.stage, 0.0) + c.cost
    total = UsageRow("", "", "")
    for c in records:
        _add(total, c)
    as_dict = lambda r: {k: v for k, v in asdict(r).items()}
    return {
        "rows": [as_dict(r) for r in rows],
        "postings": sorted(postings.values(), key=lambda p: -p["cost"]),
        "total": {k: v for k, v in asdict(total).items() if k not in ("basis", "model", "stage")},
        "measured_calls": sum(c.basis == "실측" for c in records),
        "prices": {m: {"input": i, "cached_input": ci, "output": o} for m, (i, ci, o) in PRICES.items()},
        "prices_as_of": PRICES_AS_OF,
    }
