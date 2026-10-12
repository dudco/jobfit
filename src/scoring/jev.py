"""판단 전용 모델(JEV, TypeSafe) 판정 어댑터 — 스펙 06 실험용. 기본 판정 경로는 바꾸지 않는다.

JEV는 글을 생성하지 않고 정해진 선택지의 확률만 돌려준다. 그래서
- 요건마다 '상태'를 5개 선택지(Choice)로 묻고,
- '근거 줄'을 이력서 줄 번호(L01…) + none 선택지로 묻는다 → 인용이 이력서 원문에서 나오는 것이 구조적으로 보장된다.
결과는 LLM 판정과 같은 LLMJudgeOutput으로 바꿔, 검증·규칙·집계를 그대로 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Optional

from preprocessing.criteria import PostingCriteria, Requirement

from .candidate import Candidate, render_lines
from .derive import DERIVED_FLAG
from .judge import LLMJudgeOutput, LLMJudgment, context_lines

PRICE_PER_MTOK = 0.042        # 입력 토큰 100만 개당 USD (2026-09 공개 가격, 출력 무료)

STATUS_LABELS = {
    "met": "이력서에 요건을 충족한다는 사실이 있다",
    "partial": "일부만 충족한다 (기간·수준 부족, 인접 분야 경험, 기술·키워드를 나열만 함)",
    "unmet": "이력서가 요건과 어긋나는 사실을 말한다 (다른 전공, 불가하다고 밝힘, 기한 초과, 미보유를 밝힘)",
    "unknown": "이력서에 판단할 정보가 없다",
    "not_applicable": "요건의 대상 조건('~의 경우')에 지원자가 해당하지 않음이 이력서로 확인된다",
}
RULES = (
    "이력서에 쓰인 사실만으로 판단한다. 같은 뜻의 다른 표현·상위 개념은 인정한다. 학력 요건은 그 수준 이상이면 충족. "
    "[기술] 줄에만 있으면 partial을 넘지 않는다. 거주 요건은 `posting`의 근무지 기준(같은 시·군 met, 인접 partial). "
    "지원자는 `posting`의 평가 모집분야에 지원한 것으로 본다."
)


def _requirement_text(r: Requirement) -> str:
    tag = "필수" if r.priority == "must" else "우대"
    scope = ", ".join(r.positions) if r.positions else "전체"
    text = f"「{r.text}」 ({tag} · {r.category} · 모집분야: {scope})"
    if DERIVED_FLAG in r.flags:
        text += " — 희망 분야와 상관없이 이 분야에 지원한다고 보고 판단, not_applicable 쓰지 않음"
    return text


def build_questions(criteria: PostingCriteria, candidate: Candidate, requirements: list[Requirement],
                    positions: Optional[list[str]]):
    """(state, questions). 질문 ID는 '{요건}__status', '{요건}__evidence'."""
    from typesafe_sdk import Choice   # 선택 의존성 — 실험할 때만 설치 (`uv pip install typesafe-sdk`)

    lines = render_lines(candidate)
    posting = "\n".join([f"공고: {criteria.title}", f"직군: {criteria.job_family}", *context_lines(criteria, positions)])
    state = {"posting": posting, "resume": "\n".join(f"L{i:02d} {line}" for i, line in enumerate(lines, start=1))}
    evidence = {f"L{i:02d}": line for i, line in enumerate(lines, start=1)}
    evidence["none"] = "판정의 근거가 되는 줄이 없다"
    questions = {}
    for r in requirements:
        questions[f"{r.id}__status"] = Choice(
            instructions=f"`resume`(지원자 이력서)가 채용 요건 {_requirement_text(r)}을 충족하는가? {RULES}",
            criteria=STATUS_LABELS)
        questions[f"{r.id}__evidence"] = Choice(
            instructions=f"채용 요건 {_requirement_text(r)}의 판정 근거가 되는 `resume`의 줄은?",
            criteria=evidence)
    return state, questions


def _get(answer, key):
    return answer[key] if isinstance(answer, dict) else getattr(answer, key)


def to_output(requirements: list[Requirement], candidate: Candidate, answers: dict):
    """JEV 답 → (LLMJudgeOutput, {요건: 확률·확신도}). 인용은 고른 줄의 원문 그대로."""
    lines = render_lines(candidate)
    judgments, details = [], {}
    for r in requirements:
        status, evidence = answers[f"{r.id}__status"], answers[f"{r.id}__evidence"]
        line_id = _get(evidence, "choice")
        quote = []
        if line_id != "none" and line_id[1:].isdigit() and 1 <= int(line_id[1:]) <= len(lines):
            quote = [lines[int(line_id[1:]) - 1]]
        exp_index = [int(quote[0].split()[1].rstrip("]"))] if quote and quote[0].startswith("[경력 ") else []
        conf = float(_get(status, "confidence"))
        judgments.append(LLMJudgment(requirement_id=r.id, quotes=quote,
                                     reason=f"JEV 판정 (확신도 {conf:.2f})", status=_get(status, "choice"),
                                     relevant_experience=exp_index))
        details[r.id] = {"confidence": conf, "probabilities": dict(_get(status, "probabilities")),
                         "evidence_confidence": float(_get(evidence, "confidence"))}
    return LLMJudgeOutput(judgments=judgments), details


class CachedJev:
    """JEV 응답 디스크 캐시 (ADR-0014와 같은 방식). 같은 state·질문·모델이면 다시 부르지 않는다."""

    def __init__(self, client_factory: Callable, cache_dir: Path, *, model: str):
        self._factory, self._client = client_factory, None
        self.cache_dir, self.model = cache_dir, model

    def ask(self, state: dict, questions: dict, *, tag: str) -> dict:
        payload = json.dumps({"model": self.model, "state": state,
                              "questions": {k: {"instructions": str(v.instructions), "criteria": dict(v.criteria)}
                                            for k, v in sorted(questions.items())}},
                             ensure_ascii=False, sort_keys=True)
        path = self.cache_dir / f"{tag}-{hashlib.sha256(payload.encode()).hexdigest()[:16]}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if self._client is None:
            self._client = self._factory()
        started = time.perf_counter()
        resp = self._client.system_one(state=state, questions=questions, model=self.model)
        elapsed = time.perf_counter() - started
        record = {
            "model": resp.model, "latency_s": round(elapsed, 3),
            "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
            "answers": {k: {"choice": a.choice, "confidence": a.confidence, "probabilities": dict(a.probabilities)}
                        for k, a in resp.answers.items()},
        }
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return record


def real_client():
    from typesafe_sdk import TypeSafeClient   # TYPESAFE_API_KEY 환경변수(.env)

    return TypeSafeClient()
