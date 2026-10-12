# ADR-0006: 소스는 `src/` 바로 아래에 둔다 (패키지 네임스페이스 없음)

- 상태: 채택
- 날짜: 2026-10-12
- 관련 스펙: 01 (계획 01 Task 1–8 이후 적용)

## 맥락

계획 01은 `src/jobfit/` 아래에 패키지를 두는 구조로 작성·구현되었다 (`from jobfit.crawler import …`). 코드 규모가 작고 배포 대상이 아닌 실행형 프로젝트라, 디렉터리 한 단계와 패키지 이름 접두어가 탐색·import에 불필요한 깊이를 더한다는 판단이 나왔다.

## 결정

```
src/
  settings.py
  cli.py
  crawler/          saramin.py, images.py, snapshot.py, service.py
  (이후) preprocessing/, scoring/, api.py
```

- import는 최상위 이름으로 쓴다: `from crawler import service`, `from settings import load_settings`, `import cli`.
- 패키지 안에서는 상대 import를 유지한다 (`crawler/service.py`의 `from . import saramin`).
- 설치는 hatchling의 `sources = ["src"]`로 `src/` 아래를 최상위 모듈로 매핑한다. 콘솔 명령은 `jobfit = "cli:app"`.
- 테스트는 `pythonpath = ["src"]`로 설치 없이도 import된다.

## 검토한 대안

- **`src/jobfit/` 패키지 유지** — 이름 충돌이 없고 파이썬 패키징 관례에 맞지만, 이 프로젝트는 라이브러리로 배포하지 않는다.
- **레포 루트에 모듈 배치 (`src/` 없음)** — 테스트가 설치되지 않은 소스를 실수로 import하는 문제를 `src/` 레이아웃이 막아 주므로 `src/`는 유지한다.

## 결과

- 얻는 것: 경로가 짧아지고(`src/crawler/service.py`), 단계별 디렉터리(`crawler/`, `preprocessing/`, `scoring/`)가 최상위에서 바로 보인다.
- 감수하는 것: `cli`, `settings`, `crawler` 같은 **일반적인 이름이 최상위 모듈로 설치**된다. 같은 가상환경에 같은 이름의 모듈이 있으면 충돌한다. → 프로젝트 전용 가상환경(`.venv`)에서만 실행한다. 라이브러리로 배포해야 하는 시점이 오면 이 ADR을 대체해 패키지 네임스페이스를 도입한다.
