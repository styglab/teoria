# Configuration

애플리케이션 설정은 `teoria.config.Settings`에서 `TEORIA_` 환경변수로 일관되게 읽는다. 비밀값은 Registry나 설정 모델에 저장하지 않고 `SecretProvider`를 통해 실행 시점에만 조회한다.

## Python 환경과 의존성

Python과 패키지는 uv로 관리한다. `pyproject.toml`은 허용 범위를, Git에 커밋하는 `uv.lock`은 직접·간접 의존성의 실제 설치 버전을 정의한다. `.python-version`은 기본 Python 3.12를 지정하며 `.venv/`는 uv가 생성하므로 커밋하지 않는다.

```bash
uv sync --locked
uv run --locked pytest
uv run --locked teoria validate registries
```

런타임 패키지는 `[project].dependencies`, 테스트와 개발 도구는 `[dependency-groups].dev`에 둔다. 패키지는 `uv add`, 개발 패키지는 `uv add --dev`, 제거는 `uv remove`로 변경하고 갱신된 `pyproject.toml`과 `uv.lock`을 함께 커밋한다.

## 애플리케이션 설정

주요 설정:

| 환경변수 | 기본값 | 의미 |
|---|---:|---|
| `TEORIA_ENVIRONMENT` | `development` | `development`, `test`, `production` 중 하나 |
| `TEORIA_REGISTRY_PATH` | `registries` | Registry 루트 |
| `TEORIA_LOG_LEVEL` | `INFO` | 애플리케이션 로그 레벨 |
| `TEORIA_SOURCE_TIMEOUT_SECONDS` | `15` | Source 요청 한 번의 timeout |
| `TEORIA_SOURCE_MAX_ATTEMPTS` | `3` | 재시도 포함 최대 요청 횟수 |
| `TEORIA_SOURCE_MAX_PAGES` | `100` | Capability 한 번의 최대 Source 페이지 수 |
| `TEORIA_CAPABILITY_TIMEOUT_SECONDS` | `120` | Capability 전체 실행 제한 시간 |

개발·테스트 환경에서는 현재 작업 디렉터리의 `.env`를 자동으로 읽는다. 운영 환경은 프로세스 또는 배포 플랫폼의 환경변수를 사용하며, `TEORIA_ENV_FILE`을 명시한 경우에만 해당 파일을 읽는다. `TEORIA_ENV_FILE`은 명시적인 로컬 파일 경로이며 Settings 필드가 아니다. Source API 키의 이름은 각 Source Registry의 `credential_env`가 결정한다.

로컬 시작 파일은 `.env.example`을 복사한다.

```bash
cp .env.example .env
```

`.env`는 커밋하지 않는다. 운영 배포에서는 Compose, Kubernetes 또는 클라우드 secret이 동일한 환경변수 이름으로 값을 주입하도록 구성한다.

`TEORIA_REGISTRIES`는 이전 이름과의 호환을 위해 임시 지원하며 새 구성에서는 `TEORIA_REGISTRY_PATH`를 사용한다.

Source와 Capability 실행 실패는 `code`, 실행 대상, 시도 횟수, 재시도 가능 여부를 가진 구조화 오류로 전달한다. 대표 코드는 `missing_source_credential`, `source_timeout`, `source_network_error`, `source_rate_limited`, `source_unavailable`, `source_page_limit_exceeded`, `capability_timeout`이다.
