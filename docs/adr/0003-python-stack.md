# ADR-0003: Python + uv + pydantic + httpx, CLI는 Typer

- 상태: 채택
- 날짜: 2026-10-12
- 관련 스펙: 01

## 맥락

HTML 파싱, 이미지 처리, (이후) LLM 호출과 구조화 출력 검증이 필요하다. 빠르게 검증 가능한 단계별 구현이 우선이다.

## 결정

| 용도 | 선택 | 이유 |
|---|---|---|
| 언어·패키지 | Python 3.10+, uv | 이미지·HTML·LLM 생태계, 빠른 설치 |
| 데이터 모델 | pydantic v2 | 매니페스트·조건·결과의 검증과 JSON 직렬화를 한 곳에서. 이후 LLM structured output 스키마로 재사용 |
| HTTP | httpx | 동기 API가 단순하고, `MockTransport`로 네트워크 없이 수집 로직을 테스트 |
| HTML | BeautifulSoup | 정적 HTML 파싱에 충분 |
| 이미지 | Pillow | 다운로드한 바이트가 이미지인지 검증, 크기 기록 |
| CLI | Typer + rich | 타입 힌트 기반 명령 정의, 표 출력 |
| 테스트 | pytest | |
| API (이후) | FastAPI | pydantic 모델을 그대로 응답 스키마로 |

## 검토한 대안

- requests — `MockTransport` 같은 내장 테스트 전송 계층이 없어 responses 등 추가 라이브러리 필요
- Playwright — [ADR-0004](0004-crawl-detail-iframe-over-http.md) 참고

## 결과

- 단계가 늘어날 때 의존성을 그 단계에서 추가한다 (스펙 01은 LLM·FastAPI 의존성 없음).
