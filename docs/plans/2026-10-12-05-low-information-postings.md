# 05. 정보가 부족한 공고 대응 구현 계획

> **에이전트 작업자용:** 필수 하위 스킬 — `superpowers:executing-plans`로 태스크 단위로 실행한다. 단계는 체크박스(`- [ ]`)로 추적한다.

**스펙:** [2026-10-12-05-low-information-postings-design.md](../specs/2026-10-12-05-low-information-postings-design.md)

**목표:** 직무 요건이 없는 공고에서 모집분야 적합도를 도출해 점수가 갈리게 하고(B), 정보 부족을 화면에 드러내며(A), 처리할 수 없는 공고를 기본 화면에서 빼 별도 주소로 보인다(C).

| # | 태스크 | 종류 |
|---|---|---|
| 1 | 도출 규칙 `scoring/derive.py` | TDD |
| 2 | 결과 모델 확장 (`derived`, `tied_positions`, `notes`, `use_derived`, `scoring_version`) + 집계 | TDD |
| 3 | 서비스: 도출 요건 판정·분야 선택·안내·재사용 조건 | TDD |
| 4 | 검증 표시 `derived_from_position` 설명, CLI 안내·"전 분야 동일" | TDD |
| 5 | API: 기본 목록에서 제외, `/api/excluded`, `/excluded` 페이지 | TDD |
| 6 | 화면: 안내 알림, 체크박스, 분야 요약 | 작성 + 헤드리스 확인 |
| 7 | 실제 판정으로 KT&G 재매칭·기록 | 수동 (API 키) |

---

### Task 1: 도출 규칙

- [x] `tests/test_derive.py` — 직무 요건이 없을 때만(경험 유형 있음 → 안 함, 일부 분야 요건 있음 → 안 함, 모집분야 없음 → 안 함, 모든 분야에 걸린 요건은 직무 요건 아님), 분야마다 우대 요건 하나·`derived_from_position` 표시 → FAIL → `needs_position_fit()`, `position_fit_requirements()` → PASS

### Task 2: 결과 모델·집계

- [x] `Weights.use_derived`, `RequirementJudgment.derived`, `CandidateScore.tied_positions`, `MatchResult.notes`·`scoring_version`(`SCORING_VERSION = 2`, 필드가 없던 결과는 1)
- [x] `test_switched_off_derived_requirements_leave_no_trace_in_counts_or_summary` → `aggregate()`에서 끈 도출 요건은 `credit=None`, 확인 필요 수·요약에서 제외

### Task 3: 서비스

- [x] `test_posting_without_job_requirements_scores_position_fit` — 배경이 맞는 분야가 대표 분야, 적합도가 모두 확인 필요면 "전 분야 동일", 안내 문구, `rescore(use_derived=False)`로 끄면 공통 자격만
- [x] `test_posting_with_job_requirements_is_unchanged` — 판정 프롬프트에 `p1` 없음, 안내 없음
- [x] `test_old_results_are_recomputed_after_scoring_changes` — `scoring_version` 1 결과는 재사용하지 않음
- [x] 구현: `applicable(criteria, position, extra)`, `derived_requirements()`, `posting_notes()`, `_pick()`(대표 분야·동점), `verify`가 도출 표시를 판정에 옮김

### Task 4: 표시

- [x] `flags.py`에 `derived_from_position`(info) — 코드가 내는 표시는 모두 설명이 있어야 함(`test_flags`)
- [x] CLI 랭킹: 안내(`ℹ …`), 분야 칸 "전 분야 동일" (`test_ranking_shows_posting_notes_and_tied_positions`)

### Task 5: API

- [x] `test_unprocessable_postings_are_hidden_from_main_list_and_listed_separately` — 기본 목록 제외, `/api/excluded`(스냅샷만 있는 텍스트 공고 + 요건 없는 조건), `/excluded` 페이지, 기본 화면에 링크 없음
- [x] `src/web/excluded.html`

### Task 6: 화면

- [x] 안내 알림, "전 분야 동일", "모집분야 적합도 반영" 체크박스(→ `rescore`의 `use_derived`), 분야별 점수 요약
- [x] 실제 KT&G 조건 + 대역 판정으로 헤드리스 확인 (콘솔 오류 0)

### Task 7: 실제 판정 [수동 — API 키]

- [x] `jobfit match 55240124 --refresh` — 도출 요건 29개가 판정 프롬프트에 들어가 KT&G만 새로 호출 (지원자 12명, 약 $0.4). S-OIL·오리온은 `jobfit match 55189170 55162188`로 다시 계산되지만 판정 프롬프트가 같아 캐시 적중 (호출 0)
- [x] 스펙 05 5장 기록: 점수 분포, 대표 분야가 배경과 맞는지, 도출 요건 판정의 인용 (1차 — 대부분 "해당 없음"으로 판정돼 전 분야 동일)
- [x] 보정 (TDD): `test_derived_requirement_cannot_be_not_applicable`(도출 요건의 해당 없음 → 미충족), `test_derived_requirement_line_tells_judge_to_assume_that_position`(도출 요건 줄에만 판정 지시, 공통 프롬프트 불변)
- [ ] 보정 후 재실행 `jobfit match 55240124 --refresh` (약 $0.4) → 5장에 2차 결과, 스펙 05 4장 마지막 항목 체크
