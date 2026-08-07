# Configuration

```bash
cp .env.example .env
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
| `TEORIA_RUNTIME_API_ROOT_PATH` | 빈 문자열 | reverse proxy가 Runtime API 앞에 붙이는 URL 경로 |
| `TEORIA_ADMIN_API_ROOT_PATH` | 빈 문자열 | reverse proxy가 Admin API 앞에 붙이는 URL 경로 |
| `TEORIA_REGISTRY_REQUIRE_PUBLISHED` | `false` | checksum이 일치하는 Published Registry만 Runtime에서 허용 |
| `TEORIA_PIPELINE_SOURCE_TIMEOUT_SECONDS` | `30` | Connector timeout |
| `TEORIA_PIPELINE_SOURCE_MAX_ATTEMPTS` | `3` | Connector 요청 횟수 |
| `TEORIA_RUNTIME_DATA_DATABASE_URL` | Compose 내부 DB | Runtime 읽기 DB URL; 외부 DB 사용 시 read-only role URL |
| `TEORIA_PIPELINE_DATA_DATABASE_URL` | Compose 내부 DB | Pipeline migration·적재용 writer DB URL |
| `TEORIA_MCP_RUNTIME_MODE` | `remote` | MCP 실행 모드 |
| `TEORIA_MCP_RUNTIME_API_URL` | 없음 | Remote Runtime URL |
| `TEORIA_MCP_RUNTIME_API_TOKEN` | 없음 | MCP가 사용하는 Runtime API token |
| `TEORIA_MCP_RUNTIME_TIMEOUT_SECONDS` | `150` | Runtime API 호출 timeout |

로컬 Compose 암호 변수는 `.env.example`을 따른다. 공유·운영 환경에서는 managed secret으로 덮어쓴다.
`TEORIA_RUNTIME_API_TOKEN`과 `TEORIA_LOCAL_RUNTIME_DB_PASSWORD`에는 기본값이 없으며 Compose 실행 전에 반드시 설정한다.

## Secret 규칙

- Source: `TEORIA_SOURCE_<SOURCE_ID>_API_KEY`
- Connector: `TEORIA_CONNECTOR_<CONNECTOR_ID>_API_KEY`
- YAML에는 실제 값이 아닌 환경변수 이름만 기록한다.
- 로그, verification case와 archive에 키·개인정보·비공개 원본 응답을 남기지 않는다.
- Pipeline writer와 Runtime reader의 DB 계정·권한을 분리하고 MCP에는 DB 권한을 주지 않는다.
