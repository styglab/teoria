# 환경 설정과 인증정보

```bash
cp deploy/compose/.env.example deploy/compose/.env
uv sync --project backend --locked --all-extras --all-groups
```

Python 의존성은 `backend/pyproject.toml`, 잠금은 `backend/uv.lock`에 둔다.
API·MCP extra와 Worker별 dependency group으로 실행 환경을 구분한다.

현재 조달·기업 API credential은 활성 Compose 서비스에 주입하지 않는다.
법령 전용 Worker에는 `TEORIA_CONNECTOR_MOLEG_LAW_API_KEY`를 주입한다.
아래 Provider 관련 변수는 공통 엔진의 설정 참조이며 현재 수집 기능을 뜻하지 않는다.
규격서 모델 인증은 별도 `specification-model-auth` volume, parser는
`TEORIA_SPECIFICATION_PARSER_PYTHON`을 사용한다.

## 설정을 읽는 위치

| 대상 | 기준 코드·설정 |
|---|---|
| Platform·Runtime·Admin | `backend/src/teoria/settings.py` |
| Pipelines | `backend/src/teoria/integrations/data_operations/settings.py` |
| DB 연결 상한 | Platform `persistence/postgres.py`, Pipelines `persistence/connection.py`의 환경변수 |
| MCP | `backend/src/teoria/integrations/runtime_http/settings.py` |
| Compose 서비스·포트·이미지·필수 인증 | `deploy/compose/compose.yaml`, `.env.example` |
| EC2 K3s·GitHub CD | `deploy/k3s/`, `.github/workflows/deploy_k3s.yaml` |

쉘 환경변수가 env 파일보다 우선한다. Compose 밖의 실행은 `TEORIA_ENV_FILE`로 파일을
선택한다. `TEORIA_ENVIRONMENT=production`에서 파일을 명시하지 않으면 작업 디렉터리의
`.env`를 자동으로 읽지 않는다. 아래는 주요 변수의 참조이며 전체 기본값은 위 코드가 기준이다.

## 프로세스 기본값과 Compose 주입값

아래 표의 기본값은 Python 설정 모델 기준이다. Compose 전용 변수는 배포 정의의
기본값을 표시한다. `.env.example`은 설정 예이며 실제 환경변수와 Compose의 고정값·
fallback이 최종 실행값을 결정한다. 다음 차이를 먼저 확인한다.

| 설정 | Python 기본값 | 현재 Compose 주입 |
|---|---|---|
| `TEORIA_ENVIRONMENT` | `development` | Platform 서비스 `production` |
| `TEORIA_ADMIN_AUTH_MODE` | `disabled` | `bearer`; Admin token 필수 |
| `TEORIA_POLICY_MODE` | `disabled` | Runtime·Admin에 `opa` |
| `TEORIA_OPENMETADATA_ENABLED` | `false` | Admin·진단 Worker에서 기본 `true` |
| `TEORIA_OPENMETADATA_BASE_URL` | `http://localhost:8585/api` | 기본 `http://openmetadata-server:8585/api` |
| `TEORIA_OPENMETADATA_AUTH_TOKEN` | 없음 | 명시 token이 없으면 ingestion bot token fallback |
| `TEORIA_RUNTIME_ARTIFACT_STORE` | 없음 | Runtime·Admin의 `/app/runtime_artifacts` |
| `TEORIA_CONTEXT_RUNTIME_API_URL` | `http://localhost:8000` | Admin의 `http://runtime-api:8000` |
| `TEORIA_CONTEXT_RUNTIME_API_TOKEN` | 없음 | Runtime service token 주입 |
| Data DB URL | Python 설정값 없음 | 외부 URL 또는 내부 PostgreSQL의 역할별 URL |

Compose의 hostname은 내부 network용이다. 호스트에서 API를 호출할 때는 공개 nginx
주소를 사용한다. 토큰과 암호를 포함한 설정 전체를 로그에 출력하지 않는다.

### 공통·경로

| 변수 | 기본값 | 의미 |
|---|---|---|
| `TEORIA_ENVIRONMENT` | `development` | 개발·테스트·운영 구분: `development`, `test`, `production` |
| `TEORIA_ENV_FILE` | 개발 시 작업 디렉터리 `.env` | 로컬 프로세스가 읽을 환경 파일 경로 |
| `TEORIA_REGISTRY_PATH` | `backend/registries` | Platform Registry |

### Runtime·Context·정책

| 변수 | 기본값 | 의미 |
|---|---|---|
| `TEORIA_SOURCE_TIMEOUT_SECONDS` | `15` | Runtime Source timeout |
| `TEORIA_SOURCE_MAX_ATTEMPTS` | `3` | Runtime Source 요청 횟수 |
| `TEORIA_SOURCE_MAX_PAGES` | `100` | Capability 최대 페이지 |
| `TEORIA_CAPABILITY_TIMEOUT_SECONDS` | `120` | Capability deadline |
| `TEORIA_RUNTIME_API_TOKEN` | 없음 | Runtime API Bearer token |
| `TEORIA_RUNTIME_ARTIFACT_PATH` | 없음 | 단일 immutable Runtime bundle version 디렉터리 |
| `TEORIA_RUNTIME_ARTIFACT_STORE` | 없음 | atomic `active.json`을 가진 Runtime bundle store |
| `TEORIA_RUNTIME_API_ROOT_PATH` | 빈 문자열 | reverse proxy가 Runtime API 앞에 붙이는 URL 경로 |
| `TEORIA_RUNTIME_CACHE_BACKEND` | `memory` | Runtime 공유 캐시 구현: `memory`, `redis`, `disabled` |
| `TEORIA_RUNTIME_CACHE_URL` | `redis://localhost:6379/0` | Redis Runtime 캐시 접속 URL |
| `TEORIA_RUNTIME_CACHE_PREFIX` | `teoria:runtime` | Registry 버전과 Capability 키 앞에 붙는 캐시 namespace |
| `TEORIA_CONTEXT_RUNTIME_API_URL` | `http://localhost:8000` | Context Engine이 승인된 Capability를 실행할 Runtime API 내부 주소 |
| `TEORIA_CONTEXT_RUNTIME_API_TOKEN` | 없음 | Context Engine 전용 Runtime API service credential; Compose에서는 Runtime token을 주입 |
| `TEORIA_CONTEXT_RUNTIME_TIMEOUT_SECONDS` | `150` | Context Engine의 Runtime API 호출 제한시간 |
| `TEORIA_CONTEXT_MAX_PERIOD_YEARS` | `10` | Context 계획이 허용하는 최대 조회 기간 |
| `TEORIA_CONTEXT_MAX_PAGES` | `100` | Context 실행당 Runtime 페이지 상한 |
| `TEORIA_POLICY_MODE` | `disabled` | 정책 결정 방식: 개발·테스트용 `disabled`, 운영용 `opa` |
| `TEORIA_OPA_URL` | `http://localhost:8181` | OPA REST API base URL |
| `TEORIA_OPA_DECISION_PATH` | `teoria/authz/decision` | OPA Data API에서 평가할 decision document |
| `TEORIA_OPA_TIMEOUT_SECONDS` | `3` | OPA 정책 결정 제한시간. 실패·undefined decision은 fail-closed |
| `TEORIA_OPA_CONTROL_PLANE_TOKEN` | 없음 | OPA Bundle·decision log·status 관리 API 전용 bearer credential |
| `TEORIA_OPA_BUNDLE_PATH` | `/var/lib/teoria/opa/teoria.tar.gz` | Policy Control Plane이 배포할 서명 Bundle 경로 |
| `TEORIA_OPA_BUNDLE_REVISION` | `development` | Bundle manifest와 decision log에 기록할 불변 revision |
| `TEORIA_REGISTRY_REQUIRE_PUBLISHED` | `false` | 주입된 Registry catalog에 published provenance가 있는지 검사하는 개발·테스트 안전장치. 운영 Runtime은 Artifact 설정이 필수 |
| `TEORIA_RUNTIME_DATA_DATABASE_URL` | 없음 | Runtime 읽기 DB URL; 외부 DB 사용 시 read-only role URL |

### Admin·Application DB

| 변수 | 기본값 | 의미 |
|---|---|---|
| `TEORIA_ADMIN_API_ROOT_PATH` | 빈 문자열 | reverse proxy가 Admin API 앞에 붙이는 URL 경로 |
| `TEORIA_ADMIN_AUTH_MODE` | `disabled` | Admin API 인증 방식. 공유·운영 환경은 `bearer` 사용 |
| `TEORIA_ADMIN_API_TOKEN` | 없음 | `bearer` mode의 Admin API credential |
| `TEORIA_ADMIN_METADATA_PUBLIC_READ` | `false` | `true`면 메타데이터 카탈로그·상세·통합 패널·계보·프로파일의 토큰 없는 조회 허용. 데이터 샘플과 변경 API의 인증은 유지 |
| `TEORIA_ADMIN_API_ACTOR` | `system:admin` | 감사 기록에 남길 인증 principal ID |
| `TEORIA_ADMIN_API_ROLES` | `metadata_admin,metadata_reviewer,binding_reviewer,ontology_owner` | 쉼표로 구분한 Admin 승인 역할 |
| `TEORIA_ADMIN_DATA_DATABASE_URL` | 없음 | 향후 데이터 조회를 위한 read-only Data DB URL |
| `TEORIA_DATABASE_CONCURRENCY_LIMIT` | `10` | Platform event loop별·DB별 활성 연결 상한. 여러 프로세스는 상한 합산 |
| `TEORIA_APP_DATABASE_URL` | 없음 | Ontology v2, Binding, Intelligence를 저장하는 Teoria Application DB URL |

### Pipelines

| 변수 | 기본값 | 의미 |
|---|---|---|
| `TEORIA_PIPELINE_PATH` | `pipelines` | Pipeline 루트 |
| `TEORIA_PIPELINE_CONCURRENCY` | `2` | 규격서 pool 전체 동시 실행 상한. Compose Worker 자체 실행 상한에도 적용 |
| `TEORIA_PIPELINE_WORKER_CPUS` | `4` | Compose 규격서 Worker 전체 CPU 상한 |
| `TEORIA_PIPELINE_WORKER_MEMORY` | `8g` | Compose 규격서 Worker 전체 메모리 상한 |
| `TEORIA_PLATFORM_REGISTRY_PATH` | `backend/registries` | Pipeline 통합 검증 대상 |
| `TEORIA_PIPELINE_SOURCE_TIMEOUT_SECONDS` | `30` | Connector timeout |
| `TEORIA_PIPELINE_SOURCE_MAX_ATTEMPTS` | `5` | Connector의 멱등 요청 최대 시도 횟수 |
| `TEORIA_PIPELINE_SOURCE_RETRY_BACKOFF_SECONDS` | `60` | Connector 재시도 지수 backoff의 최초 대기시간 |
| `TEORIA_PIPELINE_BID_NOTICE_ENRICHMENT_REQUESTS_PER_SECOND` | `1` | 공고별 면허·지역 보강 요청의 프로세스당 초당 최대 시작 횟수 |
| `TEORIA_PIPELINE_DATABASE_CONCURRENCY_LIMIT` | `10` | Pipeline event loop별·DB별 활성 연결 상한. 여러 Worker·프로세스는 상한 합산 |
| `TEORIA_PIPELINE_DATA_DATABASE_URL` | 없음 | Pipeline migration·적재용 writer DB URL |

### MCP

| 변수 | 기본값 | 의미 |
|---|---|---|
| `TEORIA_MCP_RUNTIME_MODE` | `remote` | MCP 실행 모드 |
| `TEORIA_MCP_RUNTIME_API_URL` | 없음 | Remote Runtime URL |
| `TEORIA_MCP_RUNTIME_API_TOKEN` | 없음 | MCP가 사용하는 Runtime API token |
| `TEORIA_MCP_RUNTIME_TIMEOUT_SECONDS` | `150` | Runtime API 호출 timeout |
| `TEORIA_MCP_RUNTIME_MAX_ATTEMPTS` | `3` | MCP capability discovery의 일시 장애 포함 최대 시도 횟수 |
| `TEORIA_MCP_RUNTIME_RETRY_BACKOFF_SECONDS` | `0.25` | MCP discovery 재시도의 최초 지수 backoff 초 |

### OpenMetadata·배포

| 변수 | 기본값 | 의미 |
|---|---|---|
| `TEORIA_OPENMETADATA_ENABLED` | `false` | Admin API OpenMetadata integration 활성화 여부 |
| `TEORIA_OPENMETADATA_BASE_URL` | `http://localhost:8585/api` | OpenMetadata REST API base URL |
| `TEORIA_OPENMETADATA_AUTH_TOKEN` | 없음 | Backend 전용 OpenMetadata bot JWT. 운영에서는 조회·검토에 필요한 최소권한 별도 토큰 권장 |
| `TEORIA_OPENMETADATA_TIMEOUT_SECONDS` | `10` | OpenMetadata REST 요청 제한시간 |
| `TEORIA_OPENMETADATA_VERIFY_SSL` | `true` | OpenMetadata TLS 인증서 검증 여부 |
| `TEORIA_OPENMETADATA_DATABASE_SERVICE` | `teoria_postgresql` | 기본 Teoria PostgreSQL Database Service 이름 |
| `OPENMETADATA_VERSION` | `2.0.5` | Server와 ephemeral ingestion image에 공통 적용하는 OpenMetadata 버전 |
| `OPENMETADATA_DB_PASSWORD` | 로컬 개발값 | OpenMetadata 전용 PostgreSQL 암호 |
| `OPENMETADATA_INGESTION_BOT_TOKEN` | 없음 | 일회성 ingestion Job이 OpenMetadata REST API에 쓰는 bot JWT |
| `TEORIA_METADATA_DB_PASSWORD` | 로컬 개발값 | OpenMetadata PostgreSQL connector의 Teoria Data DB read-only 암호 |
| `TEORIA_LOCAL_PLATFORM_DB_PASSWORD` | 로컬 개발값 | Compose의 Control/Application PostgreSQL 관리 계정 암호 |

로컬 Compose 암호 변수는 `deploy/compose/.env.example`을 따른다. 공유·운영 환경에서는 managed secret으로 덮어쓴다.
`TEORIA_ADMIN_API_TOKEN`, `TEORIA_RUNTIME_API_TOKEN`, `TEORIA_OPA_CONTROL_PLANE_TOKEN`과
`TEORIA_LOCAL_RUNTIME_DB_PASSWORD`에는 기본값이 없으며 Compose 실행 전에 반드시 설정한다.
Compose의 Admin API는 `bearer`로 고정한다. `TEORIA_ADMIN_AUTH_MODE=disabled`는
호스트 개발용 설정이며 Compose 인증을 비활성화하지 않는다.
`.env.example`에는 Compose가 실제로 받는 입력값만 둔다.
컨테이너 내부 OpenMetadata 주소는 `http://openmetadata-server:8585/api`다.

## 호스트에서 직접 실행

호스트 프로세스는 각 프로젝트의 Settings 기본값과 명시한 환경 파일을 사용한다.
Compose 입력 파일을 재사용하면 컨테이너 전용 주소를 호스트 주소로 덮어써야 한다.
로컬 Python 실행용 `TEORIA_ENVIRONMENT=development`, 경로와 timeout 기본값은 Settings가 소유한다.

```bash
TEORIA_ENV_FILE=deploy/compose/.env \
TEORIA_ADMIN_AUTH_MODE=bearer \
TEORIA_OPENMETADATA_BASE_URL=http://localhost:8585/api \
  uv run --locked --project backend --extra api teoria-admin-api
```

이 예시는 주소·인증 차이를 보여준다. DB를 사용하는 호스트 실행은 별도 접근 경로와
DB URL도 설정해야 한다. Compose 내부 DB 포트를 기본 공개하지 않는다.
독립적인 호스트 개발 환경 파일을 쓰면 `TEORIA_ENV_FILE`로 그 파일을 선택한다.

## 자산 진단 Worker 설정

| 변수 | 기본값 | 의미 |
|---|---|---|
| `TEORIA_ASSESSMENT_ENABLED` | `false` | 진단 요청 활성화 |
| `TEORIA_ASSESSMENT_MODEL_URL` | 없음 | gateway의 전체 chat-completions endpoint |
| `TEORIA_ASSESSMENT_MODEL_NAME` | 없음 | 사용할 모델 ID |
| `TEORIA_ASSESSMENT_MODEL_TOKEN` | 없음 | gateway 인증정보, Worker에만 전달 |
| `TEORIA_ASSESSMENT_MODEL_TIMEOUT_SECONDS` | `90` | 모델 요청 제한시간 |
| `TEORIA_ASSESSMENT_MODEL_MAX_TOKENS` | `6000` | 출력 한도, 모델 문맥 크기에 맞게 조정 |

요청·응답 계약과 시작 방법은 [자산 진단](../platform/metadata/asset_assessment.md)을 따른다.

## Secret 규칙

- Source: `TEORIA_SOURCE_<SOURCE_ID>_API_KEY`
- Connector: `TEORIA_CONNECTOR_<CONNECTOR_ID>_API_KEY`
- YAML에는 실제 값이 아닌 환경변수 이름만 기록한다.
- 로그, verification case와 archive에 키·개인정보·비공개 원본 응답을 남기지 않는다.
- Pipeline writer와 Runtime reader의 DB 계정·권한을 분리하고 MCP에는 DB 권한을 주지 않는다.
- Runtime bearer token은 service authentication이며 최종 사용자 권한을 대신하지 않는다.
  사용자 principal과 role은 신뢰된 Admin/MCP gateway가 Runtime으로 전달하고 OPA가
  Capability와 Context 정책을 결정한다. 운영 gateway에 OIDC를 연결하기 전에는
  외부 사용자가 identity 전달 header를 직접 설정할 수 없도록 한다.
- OPA signing private key는 `opa-signing-keys` volume 또는 외부 secret manager에만
  보관하고 이미지, Git, 일반 로그에 포함하지 않는다. 공유 환경에서는 revision을
  소스 commit 또는 policy release ID로 고정한다.

K3s는 Compose `.env`를 자동으로 읽지 않는다. 역할별 Secret 참조와 GitHub Environment 설정은
[EC2 K3s 배포](k3s.md)를 따른다.
