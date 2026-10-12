# ADR-0003: Python + uv + pydantic + httpx, CLI는 Typer

- 상태: 채택
- 날짜: 2026-10-12
- 관련 스펙: 01

## 맥락

세 단계에 필요한 작업은 다음과 같다.

| 단계 | 필요한 것 |
|---|---|
| ① 수집 | HTTP 요청, HTML 파싱, 이미지 바이트 검사 |
| ② 전처리·구조화 | 이미지 가공(리사이즈·분할), 비전 LLM 또는 OCR, LLM 구조화 출력과 검증 |
| ③ 스코어링 | LLM 판정, 점수 계산, 목업 데이터로 반복 보정 |

규모는 작다(공고 2건, 지원자 12명). 처리 시간의 대부분은 LLM 응답 대기이고, 동시성·처리량은 병목이 아니다. 대신 프롬프트·가중치를 바꿔 보며 결과를 들여다보는 **반복 실험의 속도**가 중요하다.

## 언어 선택: 왜 Python인가

후보는 Python, Node(TypeScript), Java, Go였다. 수집(①)은 어느 언어로도 쉽다. 차이는 ②·③에서 난다.

| 기준 | Python | Node (TS) | Java | Go |
|---|---|---|---|---|
| 이미지 처리 | Pillow — 표준적, 투명도·GIF·분할 다루기 쉬움 | sharp — 빠르고 충분함 | ImageIO/TwelveMonkeys — 장황함 | 표준 `image` — 기본 기능만 |
| OCR·비전 대안 | Tesseract 바인딩, PaddleOCR, EasyOCR 모두 Python 우선 | tesseract.js 정도 | Tess4J | 바인딩 빈약 |
| LLM SDK·구조화 출력 | 공식 SDK가 pydantic 모델을 그대로 응답 스키마로 받음 | 공식 SDK + zod로 동등 | 공식 SDK 있으나 스키마 연동이 번거로움 | 공식 SDK 있으나 구조화 출력 도구가 덜 성숙 |
| 스키마 하나로 검증·직렬화·LLM 스키마 | pydantic | zod | Jackson + 별도 스키마 | struct 태그 + 별도 스키마 |
| 실험·보정 반복 | REPL, 짧은 스크립트로 결과 확인 | 가능 | 컴파일·보일러플레이트 부담 | 가능하나 데이터 탐색 도구 부족 |
| 장점이 사는 상황 | 데이터·ML 중심 작업 | UI와 언어 공유, 프론트 중심 팀 | 대규모 서비스, 강한 타입·생태계 | 고성능 동시 처리, 단일 바이너리 배포 |

판단:

- **Go, Java**: 강점(동시성, 처리량, 대규모 서비스 구조, 단일 바이너리 배포)이 이 규모에서는 쓰이지 않는다. 반면 이미지·OCR·LLM 구조화 출력 쪽 도구가 약하거나 장황해서, 정작 어려운 ②·③에서 비용이 커진다.
- **Node(TypeScript)**: 가장 가까운 대안이다. 공식 LLM SDK와 zod 조합은 pydantic과 거의 동등하고, sharp도 충분하다. UI와 언어를 공유할 수 있다는 장점도 있다. 다만 UI는 결과를 보여주는 정적 페이지 수준이라 언어 공유의 이득이 작고, ②에서 OCR 등 대안을 시험해야 할 경우 선택지가 Python 쪽에 몰려 있다.
- **Python**: ②·③의 도구(Pillow, OCR 대안, LLM SDK + pydantic)가 가장 두껍고, 결과를 바로 열어 보며 고치는 실험 루프가 가장 짧다.

결론: **어려운 부분(이미지 → 조건, 점수 보정)의 도구와 실험 속도를 기준으로 Python을 택한다.**

## 결정

| 용도 | 선택 | 이유 |
|---|---|---|
| 언어·패키지 | Python 3.10+, uv | 위 "언어 선택" 참고. uv는 가상환경·의존성 설치가 빠르고 lock이 재현 가능 |
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

- 얻는 것: ②·③에서 도구 선택지가 넓고, 실험·보정 반복이 빠르다. pydantic 모델 하나로 저장 형식·API 응답·LLM 출력 스키마를 겸한다.
- 감수하는 것:
  - 동적 타입 → 타입 힌트와 pydantic 런타임 검증으로 경계(파일·LLM 출력·API)에서 막는다.
  - 실행에 Python 환경이 필요하다 → uv로 설치를 한 줄로 줄이고, README에 실행 방법을 명시한다.
  - 처리량이 커지면(공고·지원자 수천 건) 동시성 설계가 필요하다 → 현재 범위 밖. LLM 호출 병렬화는 asyncio(httpx·SDK 모두 지원)로 대응 가능하다.
- 단계가 늘어날 때 의존성을 그 단계에서 추가한다 (스펙 01은 LLM·FastAPI 의존성 없음).
