# ADR (Architecture Decision Records)

되돌리기 어렵거나 이후 설계를 제약하는 결정을, 그 시점의 근거와 함께 기록한다. 결정이 바뀌면 기존 ADR을 고치지 않고 새 ADR을 쓰고 이전 것을 `대체됨(ADR-XXXX)`으로 표시한다.

| # | 제목 | 상태 | 관련 스펙 |
|---|---|---|---|
| [0001](0001-three-stage-delivery.md) | 수집 → 전처리·구조화 → 스코어링 3단계로 나눠 구현 | 채택 | 전체 |
| [0002](0002-thin-entrypoints.md) | CLI·API·UI는 같은 서비스를 호출하는 얇은 어댑터 | 채택 | 전체 |
| [0003](0003-python-stack.md) | Python + uv + pydantic + httpx, CLI는 Typer | 채택 | 01 |
| [0004](0004-crawl-detail-iframe-over-http.md) | 사람인 상세 본문은 iframe 문서를 HTTP로 직접 수집 (브라우저 자동화·공식 API 미사용) | 채택 (실 페이지 검증됨) | 01 |
| [0005](0005-origin-snapshot.md) | 공고 원본을 스냅샷(원본 바이트 + 매니페스트)으로 보존하고 단계 간 계약으로 삼는다 | 채택 | 01 |
| [0006](0006-flat-src-layout.md) | 소스는 `src/` 바로 아래에 둔다 (패키지 네임스페이스 없음) | 채택 | 01 |
| [0007](0007-data-not-versioned.md) | `data/`(수집·처리 산출물)는 버전 관리하지 않는다 | 채택 | 01 |
| [0008](0008-image-only-conditions.md) | 매칭 조건은 공고 이미지에서만 얻는다 (페이지 텍스트·숨김 키워드 미사용) | 채택 | 01·02·03 |
| [0009](0009-evaluation-postings.md) | 평가용 공고 2건 — S-OIL 사무직(55189170), 오리온 생산직(55162188) | 채택 | 01·02·03 |
| [0010](0010-vision-llm-extraction.md) | 공고 이미지 읽기는 비전 LLM으로 한다 (OCR 엔진·규칙 기반 미채택) | 채택 (실험 검증 조건부) | 02 |
| [0011](0011-transcribe-then-structure.md) | 전사(읽기)와 구조화(이해)를 나누고, 결과를 코드로 검증한다 | 채택 | 02 |
| [0012](0012-whitespace-aware-slicing.md) | 긴 공고 이미지는 글자 줄 사이 여백에서 자른다 | 채택 (실험으로 확정) | 02 |
| [0013](0013-requirement-model.md) | 요건은 "유형 고정 + 모집분야 범위" 구조로 표현한다 | 채택 | 02·03 |
| [0014](0014-llm-response-cache.md) | LLM 응답을 입력 해시로 디스크에 캐시한다 | 채택 | 02·03 |
| [0015](0015-judge-then-aggregate.md) | 매칭은 LLM이 요건별로 판정하고, 점수는 코드가 집계한다 | 채택 | 03 |
| [0016](0016-candidate-model-and-mock-dataset.md) | 이력서는 반정형 JSON(= 이력서 전처리 결과 계약) + 줄 번호 렌더링, 목업 12건은 레포에 둔다 | 채택 | 03 |
| [0017](0017-score-formula.md) | 점수식 — 필수·우대 가중 평균 × 필수 미충족 게이트, "모름"은 절반 | 채택 (상수는 실험으로 보정) | 03 |
| [0018](0018-statutory-preferences-not-scored.md) | 법정 우대(국가보훈·장애인)는 점수에 반영하지 않고 이력서에서 받지 않는다 | 채택 | 02·03 |

## 템플릿

```markdown
# ADR-NNNN: 제목

- 상태: 제안 | 채택 | 폐기 | 대체됨(ADR-XXXX)
- 날짜: YYYY-MM-DD
- 관련 스펙: NN

## 맥락
## 결정
## 검토한 대안
## 결과 (얻는 것 / 감수하는 것)
```
