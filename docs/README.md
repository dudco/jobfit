# 문서

| 문서 | 내용 |
|---|---|
| [architecture.md](architecture.md) | 전체 구조 — 진입점(CLI·API·UI)과 3단계 파이프라인 |
| [specs/](specs/) | 단계별 설계 문서 — 무엇을, 왜, 어떤 범위로 |
| [plans/](plans/) | 스펙별 구현 계획 — 태스크·스텝 단위 TDD 절차 |
| [adr/](adr/README.md) | 아키텍처 결정 기록 |

## 진행 방식

구현은 **수집 → 전처리·구조화 → 스코어링** 세 단계로 나눈다 ([ADR-0001](adr/0001-three-stage-delivery.md)). 단계마다 **스펙 → 구현 계획 → TDD 실행 → 관찰 기록** 순서로 진행하고, 다음 단계 스펙은 직전 단계의 실제 산출물을 보고 쓴다.

## 파일 이름 규칙

- 스펙: `specs/YYYY-MM-DD-NN-<주제>-design.md`
- 계획: `plans/YYYY-MM-DD-NN-<주제>.md` — 대응 스펙과 같은 번호·주제
- ADR: `adr/NNNN-<주제>.md`
- `NN`은 작성 순서 일련번호다. 날짜가 바뀌어도 리셋하지 않고 이어서 증가한다.

## 진행 현황

| # | 단계 | 스펙 | 계획 | 상태 |
|---|---|---|---|---|
| 01 | 공고 이미지 수집 | [spec](specs/2026-10-12-01-posting-crawler-design.md) | [plan](plans/2026-10-12-01-posting-crawler.md) | 완료 |
| 02 | 이미지 전처리·구조화 | [spec](specs/2026-10-12-02-posting-preprocessing-design.md) | [plan](plans/2026-10-12-02-posting-preprocessing.md) | 완료 |
| 03 | 지원자 매칭 스코어링 | [spec](specs/2026-10-12-03-candidate-scoring-design.md) | [plan](plans/2026-10-12-03-candidate-scoring.md) | 완료 |
| 04 | API · UI | [spec](specs/2026-10-12-04-api-and-ui-design.md) | [plan](plans/2026-10-12-04-api-and-ui.md) | 초안 — 검토 대기 |
