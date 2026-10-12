# ADR (Architecture Decision Records)

되돌리기 어렵거나 이후 설계를 제약하는 결정을, 그 시점의 근거와 함께 기록한다. 결정이 바뀌면 기존 ADR을 고치지 않고 새 ADR을 쓰고 이전 것을 `대체됨(ADR-XXXX)`으로 표시한다.

| # | 제목 | 상태 | 관련 스펙 |
|---|---|---|---|
| [0001](0001-three-stage-delivery.md) | 수집 → 전처리·구조화 → 스코어링 3단계로 나눠 구현 | 채택 | 전체 |
| [0002](0002-thin-entrypoints.md) | CLI·API·UI는 같은 서비스를 호출하는 얇은 어댑터 | 채택 | 전체 |
| [0003](0003-python-stack.md) | Python + uv + pydantic + httpx, CLI는 Typer | 채택 | 01 |
| [0004](0004-crawl-detail-iframe-over-http.md) | 사람인 상세 본문은 iframe 문서를 HTTP로 직접 수집 (브라우저 자동화·공식 API 미사용) | 채택 (실 페이지 검증 조건부) | 01 |
| [0005](0005-origin-snapshot.md) | 공고 원본을 스냅샷(원본 바이트 + 매니페스트)으로 보존하고 단계 간 계약으로 삼는다 | 채택 | 01 |

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
