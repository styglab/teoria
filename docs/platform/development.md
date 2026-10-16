# Platform 개발 안내

Platform은 업무 의미를 정의하고 사용자 요청을 실행한다. OpenMetadata 자산을 조회하고,
Ontology와 연결하며, AI 제안을 검토·적용하고, 게시된 계약으로 Capability를 실행한다.
데이터를 계속 수집하는 작업은 [Pipelines](../pipelines/development.md)가 담당한다.

## 먼저 찾을 위치

아래 경로는 `platform/` 기준이다.

| 목적 | 위치와 책임 |
|---|---|
| 실행 명령 | `pyproject.toml`의 scripts, `src/teoria/entrypoints/` |
| 관리 명령 | `src/teoria/cli/`: 인자 정의와 기능별 실행 함수 |
| Admin HTTP API | `src/teoria/admin/`: 인증, Router와 서비스 조립 |
| Ontology 작성·게시 | `src/teoria/ontology/`, `src/teoria/authoring/` |
| Semantic Binding | `src/teoria/binding/` |
| 자산 맥락·OpenMetadata client | `src/teoria/metadata/` |
| 자산 진단·제안 처리 | `src/teoria/intelligence/asset_assessment/`, `suggestions/` |
| Source·Mapping·Capability 실행 | `src/teoria/runtime/` |
| 질문 계획·실행 정책 | `src/teoria/context/` |
| OPA 정책 연계 | `src/teoria/policy/` |
| 업무별 구현 | `src/teoria/domains/` |
| Registry 로딩·검증·발행 | `src/teoria/registry/` |
| 선언형 실행 계약 | `registries/` |
| Application DB migration | `database/migrations/` |
| 관리자 화면 | `admin_ui/src/features/` |

## 실행 진입점

| 명령 | 용도 | 내부 진입점 |
|---|---|---|
| `teoria` | 검증, Registry 발행, bundle 구성, 이관·관리 | `entrypoints/cli.py` |
| `teoria-admin-api` | 자산·Ontology·Binding·제안 관리 | `entrypoints/admin_api.py` |
| `teoria-runtime-api` | Capability discovery와 실행 | `entrypoints/runtime_api.py` |
| `teoria-metadata-assessment-worker` | 비동기 자산 진단 | `entrypoints/asset_assessment_worker.py` |
| `teoria-policy-control-plane` | 서명 정책 bundle·로그·상태 처리 | `entrypoints/policy_control_plane.py` |

CLI는 `cli/parser.py`에서 인자를 정의하고 `entrypoints/cli.py`에서 명령을 연결한다.
Registry·artifact는 `cli/registry.py`, Ontology는 `cli/ontology.py`, Binding은
`cli/binding.py`, DB migration은 `cli/database.py`, Source 검증은
`cli/source_verification.py`가 소유한다. 조달 데이터 진단 명령은 해당 Domain의
`cli.py`에 둔다.

Admin의 `api.py`는 HTTP 앱을 만들고 `composition.py`의 `create_admin_services()`가
서비스를 생성한다. `install_admin_routers()`는 구성한 서비스를 Router에 연결한다.
새 API는 기능별 Router에 추가하고 모든 업무 로직을 앱 진입점에 모으지 않는다.

## I/O와 동시 실행

HTTP·DB 호출은 API → Service → Repository까지 `await`로 연결한다.
PostgreSQL은 `persistence/postgres.py`의 `connect()`와 Psycopg `AsyncConnection`을
사용한다. 연결을 빠져나가면 성공 시 commit, 예외·취소 시 rollback하고 연결을 닫는다.
한 transaction의 SQL 실행 순서와 승인·효과 기록 경계를 유지한다.

`TEORIA_DATABASE_CONCURRENCY_LIMIT`는 event loop별·접속 URL별 활성 연결 상한이며 기본값은
10이다. 프로세스가 여러 개면 각 프로세스의 상한이 합산되므로 DB 전체 연결 예산에
맞춰 설정한다. 연결을 재사용하는 pool은 아니며 연결을 요청·Task 사이에 공유하지 않는다.

독립 조회만 제한된 범위에서 병렬 실행한다. 정규화·계산·검증은 일반 함수로 유지한다.
동기 SDK는 제한된 thread 또는 별도 Job으로 격리하며 `async def` 안에서 직접 실행하지 않는다.
CLI는 프로세스 진입점에서만 `asyncio.run()`으로 비동기 작업을 실행한다.
[Psycopg 비동기 연결](https://www.psycopg.org/psycopg3/docs/advanced/async.html)의
connection·cursor context와 취소 동작을 따른다.

## Domain 기능을 추가하는 방법

`src/teoria/domains/company/identity/`는 기업 식별을, `public_procurement/`는
조달 질문 해석·시장 분석·분류·탐색을 소유한다.
`legal_information/`은 수집된 법령을 Admin 진단에서 검색한다.

Domain의 `processors.py`에서 Capability handler와 query 후처리를 등록하고
`runtime/composition.py`에서 조립한다. Registry 문자열을 임의 Python import 경로로
실행하지 않는다. Context의 기본 query handler는 `context/composition.py`가 선택한다.
공통 Context Engine은 의미 조회·계획 검증·실행 정책을, Domain handler는 질문 해석과
결과 집계를 담당한다. 새 기능을 위해 공통 Runner에 Domain별 분기를 추가하지 않는다.

기존 `assessment.*`, `market_context.*`, `company_identity.*` processor ID는 게시된
계약의 식별자다. Python 모듈을 옮긴다는 이유로 바꾸지 않는다. 업무 Domain과
Runtime 계약 namespace의 차이는 [Registry 안내](registry/guide.md)를 참고한다.

값 변환 위치도 구분한다. Provider 응답을 정규 DB 행으로 만드는 코드는 Pipelines의
기능별 `normalization.py`, Source record를 Runtime 값으로 만드는 codec은
`src/teoria/runtime/mapping/transforms/`에 둔다.

## 개발 실행과 검증

저장소 루트에서 의존성과 [환경 설정](../deployment/configuration.md)을 준비한다.
Admin API의 기본 포트는 8001, Runtime API는 8000이다. 전체 스택을 사용하려면
[시작 안내](../platform-guide.md)를 따른다.

```bash
uv run --locked --package teoria-platform teoria-admin-api
```

변경 후 단위·통합 테스트와 Registry 검증을 실행한다.

```bash
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-platform teoria validate platform/registries
```

Application DB 통합 테스트는 운영과 분리된 DB의 `TEORIA_TEST_APP_DATABASE_URL`을
사용한다. 설정이 없으면 DB 의존 테스트가 건너뛰어질 수 있다. CI의
`platform-app-integration` Job은 migration·동시 승인·게시·제안 적용 복구를 검증한다.
Application DB migration은 새 순번 파일을 추가하고 Compose 설정도 검사한다.

```bash
uv run --locked --package teoria-platform pytest platform/tests/integration
docker compose -f deploy/compose/compose.yaml config --quiet
```

## 작업별 상세 안내

- 의미 모델을 바꾸려면 [Ontology와 Binding](ontology.md)을 읽는다.
- 실행 계약을 바꾸려면 [Registry](registry/guide.md), 실행·게시 경로는 [Runtime](runtime.md)을 읽는다.
- 질문 계획·정책·실행은 [Context](context.md)를 읽는다.
- 자산 조회는 [자산 맥락](metadata/asset_context.md), 분석은 [자산 진단](metadata/asset_assessment.md), 승인·적용·복구는 [제안](metadata/suggestions.md)을 읽는다.
- 화면 개발은 [Admin UI](admin_ui.md), 조달 계산은 [시장 분석](domains/public_procurement/market_analysis.md)을 읽는다.

