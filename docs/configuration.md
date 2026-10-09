# Configuration

```bash
cp deploy/compose/.env.example deploy/compose/.env
export TEORIA_ENV_FILE=deploy/compose/.env
uv sync --locked --all-packages --all-groups
```

의존성은 사용하는 프로젝트의 `pyproject.toml`에만 추가한다. 루트 `uv.lock`은 개발·CI 재현성을 위해 공유한다.

## 환경변수

| 변수 | 기본값 | 의미 |
|---|---:|---|
| `TEORIA_REGISTRY_PATH` | `platform/registries` | Platform Registry |
| `TEORIA_PIPELINE_PATH` | `pipelines` | Pipeline 루트 |
| `TEORIA_PLATFORM_REGISTRY_PATH` | `platform/registries` | Pipeline 통합 검증 대상 |
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
| `TEORIA_ADMIN_API_ROOT_PATH` | 빈 문자열 | reverse proxy가 Admin API 앞에 붙이는 URL 경로 |
| `TEORIA_ADMIN_AUTH_MODE` | `disabled` | Admin 쓰기 API 인증 방식. 공유·운영 환경은 `bearer` 사용 |
| `TEORIA_ADMIN_API_TOKEN` | 없음 | `bearer` mode의 Admin API credential |
| `TEORIA_ADMIN_API_ACTOR` | `system:admin` | 감사 기록에 남길 인증 principal ID |
| `TEORIA_ADMIN_API_ROLES` | Admin 역할 전체 | 쉼표로 구분한 Admin 승인 역할 |
| `TEORIA_ADMIN_DATA_DATABASE_URL` | 없음 | Admin API가 입찰 데이터 조회에 사용하는 read-only Data DB URL |
| `TEORIA_APP_DATABASE_URL` | 없음 | Ontology v2, Binding, Intelligence를 저장하는 Teoria Application DB URL |
| `TEORIA_OPENMETADATA_ENABLED` | `false` | Admin API OpenMetadata integration 활성화 여부 |
| `TEORIA_OPENMETADATA_BASE_URL` | `http://localhost:8585/api` | OpenMetadata REST API base URL |
| `TEORIA_OPENMETADATA_AUTH_TOKEN` | Compose 개발환경에서는 `OPENMETADATA_INGESTION_BOT_TOKEN` fallback | Backend 전용 OpenMetadata bot JWT. 운영에서는 조회·검토에 필요한 최소권한 별도 토큰 권장 |
| `TEORIA_OPENMETADATA_TIMEOUT_SECONDS` | `10` | OpenMetadata REST 요청 제한시간 |
| `TEORIA_OPENMETADATA_VERIFY_SSL` | `true` | OpenMetadata TLS 인증서 검증 여부 |
| `TEORIA_OPENMETADATA_DATABASE_SERVICE` | `teoria_postgresql` | 기본 Teoria PostgreSQL Database Service 이름 |
| `OPENMETADATA_VERSION` | `1.12.6` | Server와 ephemeral ingestion image에 공통 적용하는 OpenMetadata 버전 |
| `OPENMETADATA_DB_PASSWORD` | 로컬 개발값 | OpenMetadata 전용 PostgreSQL 암호 |
| `OPENMETADATA_INGESTION_BOT_TOKEN` | 없음 | 일회성 ingestion Job이 OpenMetadata REST API에 쓰는 bot JWT |
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
| `TEORIA_METADATA_DB_PASSWORD` | 로컬 개발값 | OpenMetadata PostgreSQL connector의 Teoria Data DB read-only 암호 |
| `TEORIA_LOCAL_PLATFORM_DB_PASSWORD` | 로컬 개발값 | Compose의 Control/Application PostgreSQL 관리 계정 암호 |
| `TEORIA_REGISTRY_REQUIRE_PUBLISHED` | `false` | 주입된 Registry catalog에 published provenance가 있는지 검사하는 개발·테스트 안전장치. 운영 Runtime은 Artifact 설정이 필수 |
| `TEORIA_PIPELINE_SOURCE_TIMEOUT_SECONDS` | `30` | Connector timeout |
| `TEORIA_PIPELINE_SOURCE_MAX_ATTEMPTS` | `5` | Connector의 멱등 요청 최대 시도 횟수 |
| `TEORIA_PIPELINE_SOURCE_RETRY_BACKOFF_SECONDS` | `60` | Connector 재시도 지수 backoff의 최초 대기시간 |
| `TEORIA_PIPELINE_BID_NOTICE_ENRICHMENT_REQUESTS_PER_SECOND` | `1` | 공고별 면허·지역 보강 요청의 프로세스당 초당 최대 시작 횟수 |
| `TEORIA_RUNTIME_DATA_DATABASE_URL` | Compose 내부 DB | Runtime 읽기 DB URL; 외부 DB 사용 시 read-only role URL |
| `TEORIA_PIPELINE_DATA_DATABASE_URL` | Compose 내부 DB | Pipeline migration·적재용 writer DB URL |
| `TEORIA_MCP_RUNTIME_MODE` | `remote` | MCP 실행 모드 |
| `TEORIA_MCP_RUNTIME_API_URL` | 없음 | Remote Runtime URL |
| `TEORIA_MCP_RUNTIME_API_TOKEN` | 없음 | MCP가 사용하는 Runtime API token |
| `TEORIA_MCP_RUNTIME_TIMEOUT_SECONDS` | `150` | Runtime API 호출 timeout |
| `TEORIA_MCP_RUNTIME_MAX_ATTEMPTS` | `3` | MCP capability discovery의 일시 장애 포함 최대 시도 횟수 |
| `TEORIA_MCP_RUNTIME_RETRY_BACKOFF_SECONDS` | `0.25` | MCP discovery 재시도의 최초 지수 backoff 초 |

로컬 Compose 암호 변수는 `deploy/compose/.env.example`을 따른다. 공유·운영 환경에서는 managed secret으로 덮어쓴다.
`TEORIA_RUNTIME_API_TOKEN`, `TEORIA_OPA_CONTROL_PLANE_TOKEN`과
`TEORIA_LOCAL_RUNTIME_DB_PASSWORD`에는 기본값이 없으며 Compose 실행 전에 반드시 설정한다.
Platform, Pipeline 또는 MCP를 Compose 밖에서 직접 실행할 때는
`TEORIA_ENV_FILE=deploy/compose/.env`를 명시한다.

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
