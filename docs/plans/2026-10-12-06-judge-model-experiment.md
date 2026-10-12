# 06. 판단 전용 모델(JEV) 판정 실험 구현 계획

> **에이전트 작업자용:** 필수 하위 스킬 — `superpowers:executing-plans`로 태스크 단위로 실행한다. 단계는 체크박스(`- [ ]`)로 추적한다.

**스펙:** [2026-10-12-06-judge-model-experiment-design.md](../specs/2026-10-12-06-judge-model-experiment-design.md)

**목표:** 요건 판정을 JEV로 했을 때의 품질·비용을 gpt-4.1 기준과 비교하고, 단계식 판정의 확신도 기준별 결과를 낸다. 기본 판정 경로는 바꾸지 않는다.

| # | 태스크 | 종류 |
|---|---|---|
| 1 | 판정 방식을 바꿔 끼우는 자리 `score_candidate(judge_fn=…)` | 리팩터링 (기존 테스트 유지) |
| 2 | JEV 어댑터: 질문 구성, 답 변환, 캐시 | TDD (대역) |
| 3 | 실험: 기준 비교, 단계식 계산, 보고서 저장 | TDD (대역) |
| 4 | CLI `experiment-jev`, 설정 `JOBFIT_JEV_MODEL`, 선택 의존성 `[jev]` | 작성 |
| 5 | 실제 JEV 실험·기록 | 수동 (TypeSafe API 키) |

- [x] **Task 1** — 기존 174개 테스트 그대로 통과
- [x] **Task 2** — `tests/test_jev.py`: 요건마다 상태·근거 줄 질문, 근거 선택지 = 이력서 줄 + none, 인용 = 고른 줄 원문(검증 통과), 근거 없는 충족 → 확인 필요, 캐시로 재호출 없음
- [x] **Task 3** — `test_experiment_compares_with_gpt_reference_and_computes_cascade`: 기준과 일치율, 불일치 목록(확신도 포함), 확신도 기준별 넘긴 수·일치율, 토큰, 보고서 파일
- [x] **Task 4** — `jobfit experiment-jev`, `.env.example`, `pyproject.toml [jev]`. 실제 데이터 + 대역으로 실행 확인 (질문 수 S-OIL 최대 22, KT&G 62)
- [x] **Task 5** [수동 — API 키] — 결과·판단은 스펙 06 5장, ADR-0024

```bash
uv pip install -e ".[dev,jev]"
# .env에 TYPESAFE_API_KEY=… 추가 (커밋되지 않음)
jobfit experiment-jev 55189170 55162188 55240124
```

결과(`data/experiments/jev-*.json`과 화면)를 스펙 06 5장에 기록하고, 2.3 판단 기준으로 ADR-0024 상태를 정한다.
