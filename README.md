# jobfit

이미지로 된 채용공고를 수집·파싱해 조건을 구조화하고, 지원자 풀과 매칭해 0~100점으로 랭킹하는 엔진.

```
① 수집 (crawler)  →  ② 전처리·구조화 (preprocessing)  →  ③ 스코어링 (scoring)
```

전체 구조는 [`docs/architecture.md`](docs/architecture.md), 설계 문서·결정 기록은 [`docs/`](docs/README.md)에 있다.

## 요구 사항

- Python 3.10 이상
- [uv](https://docs.astral.sh/uv/)

## 설치

```bash
git clone <repo> && cd jobfit
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

설치하면 `jobfit` 명령이 생긴다.

```bash
jobfit --help
```

> 소스는 `src/` 바로 아래에 있고 `cli`, `settings`, `crawler`가 최상위 모듈로 설치된다 ([ADR-0006](docs/adr/0006-flat-src-layout.md)). 반드시 프로젝트 전용 가상환경(`.venv`)에서 실행한다.

## 설정

환경변수 또는 레포 루트의 `.env`로 바꿀 수 있다 (`.env.example` 참고).

| 변수 | 기본값 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | — | 전처리(`extract`)·매칭(`match`)·`models`에 필요. 캐시에 있는 호출은 키 없이 동작 |
| `JOBFIT_DATA_DIR` | `<레포>/data` | 수집·처리 산출물 저장 위치 |
| `JOBFIT_REQUEST_INTERVAL` | `1.5` | 사람인 요청 사이 대기 시간(초) |
| `JOBFIT_VISION_MODEL` | `gpt-4.1` | 이미지 전사 모델 |
| `JOBFIT_TEXT_MODEL` | `gpt-4.1` | 구조화 모델 |
| `JOBFIT_SLICE_HEIGHT` | `1200` | 긴 이미지를 자르는 목표 높이(px). `0`이면 자르지 않음 |
| `JOBFIT_MAX_WIDTH` | `1000` | 이보다 넓은 이미지는 축소 |
| `JOBFIT_JUDGE_MODEL` | `gpt-4.1` | 지원자 판정 모델 (`match`) |
| `JOBFIT_CANDIDATES_DIR` | `<레포>/dataset/candidates` | 지원자 JSON 디렉터리 |

## 사용법

### 한 번에 실행 — `jobfit run`

```bash
jobfit run "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=55162188"   # 수집 → 조건 추출 → 매칭
jobfit run 55189170 55162188 --refresh     # 매칭만 다시 (수집·추출 결과는 재사용)
```

공고 URL(또는 rec_idx) 하나로 아래 1·3·6단계를 차례로 실행하고 랭킹을 보여준다. 이미 처리한 단계는 저장된 결과와 LLM 캐시를 재사용하므로 두 번째 실행부터는 API 호출이 없다. 단계별 명령은 아래에 있다.

### 화면 — `jobfit serve`

```bash
jobfit serve                  # http://127.0.0.1:8000  (API 문서: /docs)
jobfit serve --port 8080
```

- 공고 탭 → 추출된 조건(필수·우대·법정 우대·근무조건). 요건의 **원본**을 누르면 그 요건이 나온 공고 이미지 조각과 인용 문구
- 랭킹 → 지원자를 누르면 요건별 판정(충족 / 부분 / 미충족 / **확인 필요** / 해당 없음), 이력서 인용, 기여 점수, 인용된 이력서 줄 강조
- 가중치 슬라이더 → 저장된 판정으로 점수만 다시 계산해 즉시 재랭킹 (LLM 호출 없음, 저장 안 함)
- 입력창에 공고 URL을 넣고 실행 (처음 처리하는 공고는 1~2분)
- 목업의 의도 라벨은 "평가용 의도 라벨 표시"를 켤 때만 보인다
- 공고 이미지에 직무 요건이 없으면(공통 자격만) 랭킹 위에 안내가 뜨고, 모집분야 이름에서 도출한 '직무 적합도' 우대 요건이 반영된다 ("⚑ 모집분야에서 도출" 표시, 체크박스로 끔)
- 처리하지 않은 공고(텍스트 공고 등)는 기본 화면에 나오지 않는다 — **http://127.0.0.1:8000/excluded** 에서 이유와 함께 볼 수 있다

### API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/run` | `{ref, refresh}` — 수집 → 추출 → 매칭 한 번에 |
| GET | `/api/postings` | 추출된 공고 목록 (매칭 여부 포함) |
| GET | `/api/postings/{id}/criteria` | 추출된 조건 |
| GET | `/api/postings/{id}/slices/{n}` | 근거 위치의 공고 이미지 조각 (PNG) |
| GET | `/api/postings/{id}/result` | 매칭 결과 (랭킹 + 요건별 근거) |
| POST | `/api/postings/{id}/match` | `{refresh}` — 매칭 실행 |
| POST | `/api/postings/{id}/rescore` | 가중치만 바꿔 재집계 (LLM 호출 없음, 저장 안 함) |
| GET | `/api/candidates` | 지원자 목록과 판정에 쓰인 이력서 원문 |
| GET | `/api/excluded` | 처리하지 않은 공고와 이유 (화면: `/excluded`) |
| GET | `/api/flags` | 검증 표시의 이름과 뜻 |

오류는 400(입력·조건 문제, 메시지 포함), 404(결과 없음), 502(사람인·OpenAI 오류).

### 1. 공고 수집 — `jobfit crawl`

사람인 공고 URL(또는 `rec_idx` 숫자)을 넣으면, 공고 원본을 스냅샷으로 저장한다. 여러 건을 한 번에 넣을 수 있다.

```bash
jobfit crawl "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=list&rec_idx=55189170"
jobfit crawl 55189170 55162188
```

```
55189170  이미지 1장  이미지 공고  [S-OIL(주)] 2026 S-OIL 사무직 신입사원 채용(D-2) - 사람인
```

- 공식 Open API를 쓰지 않고, 공고 페이지와 상세 본문 iframe을 직접 받아 본문 이미지를 내려받는다 ([ADR-0004](docs/adr/0004-crawl-detail-iframe-over-http.md)).
- 이미 받은 공고는 네트워크 요청 없이 저장된 스냅샷을 재사용한다. 다시 받으려면 `--refresh`.
- 본문이 이미지가 아닌 공고(텍스트 공고, 이미지 없음)는 `이미지 공고 아님?` 경고와 함께 저장만 한다.

| 옵션 | 설명 |
|---|---|
| `--refresh` | 기존 스냅샷을 지우고 다시 수집 |

### 2. 저장된 공고 보기 — `jobfit postings`

```bash
jobfit postings
```

```
┃ 사이트  ┃ ID       ┃ 이미지 ┃ 이미지 공고 ┃ 수집 시각            ┃ 제목                           ┃
│ saramin │ 55162188 │ 1      │ 예          │ 2026-10-12T03:53:38… │ [(주)오리온] ㈜오리온 청주공장… │
│ saramin │ 55189170 │ 1      │ 예          │ 2026-10-12T03:36:37… │ [S-OIL(주)] 2026 S-OIL 사무직… │
```

### 3. 조건 추출 — `jobfit extract`

수집한 공고의 **이미지만으로** 조건을 구조화한다 ([스펙 02](docs/specs/2026-10-12-02-posting-preprocessing-design.md)).

```bash
jobfit extract 55189170 55162188           # --refresh: 다시 추출
```

```
이미지 정규화·분할 (Pillow) → 조각별 전사 (비전 LLM) → 구조화 (텍스트 LLM) → 인용 검증·중복 병합 (코드)
```

- 긴 이미지는 글자 줄 사이 여백에서 자른다 ([ADR-0012](docs/adr/0012-whitespace-aware-slicing.md)).
- 요건마다 근거 문장과 출처(이미지·조각 번호)가 남는다. 근거가 전사에 없으면 경고한다.
- LLM 응답은 `data/cache/llm/`에 캐시된다. 같은 입력이면 다시 호출하지 않는다 ([ADR-0014](docs/adr/0014-llm-response-cache.md)).

### 4. 추출 결과 보기 — `jobfit criteria`

```bash
jobfit criteria 55162188
```

요건(필수/우대, 유형, 적용 모집분야, 근거 위치), 모집분야, 근무조건(점수 미반영), 경고를 보여준다. `⚑`는 법정 우대 등 민감 속성 표시.

### 5. 정답 대비 평가 — `jobfit evaluate`

```bash
jobfit evaluate 55162188        # 기본 정답: tests/fixtures/criteria_truth/55162188.yaml
```

재현율·정밀도·필수 재현율·필수/우대 일치율·유형 일치율과 누락·추가·불일치 요건을 출력한다. 정답 목록은 사람이 이미지를 보고 만든 평가 전용 데이터다.

### 6. 지원자 매칭 — `jobfit match`

```bash
jobfit match 55189170 55162188        # dataset/candidates의 지원자 전원을 각 공고에 매칭 (교차 평가)
jobfit match 55189170 --candidates path/to/dir
jobfit match 55189170 --refresh       # 저장된 결과를 무시하고 다시 (판정은 LLM 캐시 사용)
```

지원자마다 요건별로 판정(충족 / 부분 / 미충족 / 확인 필요 / 해당 없음)하고, 0~100점으로 랭킹해 `data/results/`에 저장한다. 결과 표의 "의도" 열은 목업의 의도 라벨을 **표시만** 한 것이고(점수 계산은 읽지 않음), 그 아래에 의도 대비 순서·점수 구간·판정 일치율을 출력한다.

### 7. 매칭 근거 보기 — `jobfit result`

```bash
jobfit result 55189170                             # 랭킹
jobfit result 55189170 --candidate soil-partial-1  # 요건별 판정 · 이력서 근거 · 기여 점수 · 요약
```

### 기타 — `jobfit models`

```bash
jobfit models     # API 키로 사용 가능한 모델 목록
```

## 산출물

```
data/postings/saramin/{rec_idx}/
  snapshot.json     매니페스트 — 출처, 수집 시각, 파일 해시, 이미지 크기·형식
  view.html         공고 페이지 원본
  detail.html       상세 본문 iframe 원본
  images/00.png …   본문 이미지 원본 (가공하지 않음)
```

```
data/criteria/saramin/{rec_idx}/
  slices/00_00.png …   분할 조각 (이미지 번호_조각 번호)
  transcript.md        전사 전체 (조각 경계 주석 포함)
  criteria.json        구조화된 공고 조건
data/cache/llm/        LLM 응답 캐시
```

```
data/results/saramin/{rec_idx}/
  ranking.json      랭킹 + 지원자별·분야별 점수 + 요건별 판정·근거 인용·기여 점수
dataset/candidates/ 목업 지원자 12명 (레포에 포함, 이력서 전처리 결과 형식 — dataset/README.md)
```

- 스냅샷은 다음 단계(전처리)의 입력이다. 전처리는 사람인을 다시 요청하지 않는다 ([ADR-0005](docs/adr/0005-origin-snapshot.md)).
- 매칭 조건은 **이미지에서만** 만든다. HTML 텍스트(제목, 숨김 키워드 등)는 보존·표시용이다 ([ADR-0008](docs/adr/0008-image-only-conditions.md)).
- `data/`는 버전 관리하지 않는다 ([ADR-0007](docs/adr/0007-data-not-versioned.md)). 공고는 마감되면 사라지므로 로컬 `data/`를 지우지 않도록 주의한다.

`snapshot.json` 예시:

```json
{
  "schema_version": 1,
  "source": {"site": "saramin", "method": "crawl", "posting_id": "55162188",
             "url": "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=55162188"},
  "fetched_at": "2026-10-12T03:53:38+00:00",
  "title": "[(주)오리온] ㈜오리온 청주공장 생산직 채용(D-8) - 사람인",
  "images": [{"index": 0, "path": "images/00.png", "format": "PNG", "width": 720, "height": 1890,
              "sha256": "1367c62c…", "bytes": 340720,
              "source_url": "https://www.saraminimage.co.kr/recruit/bbs_recruit26/35_orionworld_img_260507.png"}],
  "skipped_images": [],
  "body_text_length": 0,
  "is_image_posting": true
}
```

## 테스트

```bash
pytest
```

네트워크·API 키 없이 돈다. 사람인 요청은 `httpx.MockTransport` 대역으로, LLM은 `tests/fakes.py`의 대역으로 바꾼다. 실제 사이트 구조는 저장해 둔 상세 HTML(`tests/fixtures/saramin_detail_real.html`)로 검증한다.

## 프로젝트 구조

```
src/
  cli.py              jobfit 명령 (run, serve, crawl, postings, extract, criteria, evaluate, match, result, models)
  api.py              HTTP API (FastAPI) — 서비스 호출만
  pipeline.py         수집 → 추출 → 매칭 한 번에 실행
  web/index.html      UI (정적 HTML 한 장, API만 호출)
  settings.py         환경변수 설정
  llm.py              LLM 프로토콜, OpenAI 구현, 응답 캐시
  crawler/
    saramin.py        사람인 HTML 규칙 (rec_idx, 본문 이미지 URL, 본문 텍스트, 제목)
    images.py         내려받은 이미지 검사
    snapshot.py       스냅샷 매니페스트와 저장
    service.py        수집 서비스 (CLI·API 공용)
  preprocessing/
    images.py         정규화·여백 기반 분할
    transcribe.py     조각별 비전 전사
    structure.py      전사 → 구조화 (LLM 출력 스키마)
    verify.py         인용 검증·중복 병합·경고
    criteria.py       PostingCriteria 모델과 저장
    evaluate.py       정답 대비 평가
    service.py        전처리 서비스 (CLI·API 공용)
  scoring/
    candidate.py      지원자 모델·줄 번호 렌더링
    judge.py          요건별 판정 (LLM)
    verify.py         판정 인용 검증·규칙 보정
    rules.py          학력 서열·경력 연수
    score.py          점수 집계·기여도·요약 (순수 함수)
    result.py         결과 모델과 저장
    evaluate.py       목업 의도 대비 평가
    service.py        매칭 서비스 (CLI·API 공용)
dataset/candidates/   목업 지원자 12명
tests/
docs/
  architecture.md     전체 구조
  specs/              단계별 설계 문서
  plans/              단계별 구현 계획
  adr/                결정 기록
```
