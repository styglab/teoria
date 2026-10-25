# Teoria MCP Gateway

현재 배포된 Runtime은 업무 Capability를 노출하지 않으므로 Tool 목록은 비어 있다.
기존 조달 Tool을 다시 노출하지 않는다. Gateway는 시작할 때 discovery를 고정하므로
Runtime bundle 변경 뒤 MCP 프로세스와 클라이언트 연결을 재시작한다.
[배포 검증](../verification/goods_focus_deployment_2026_10_25.md)에서 실제 STDIO 초기화와 빈 Tool 목록을 확인했다.

MCP는 Runtime API의 공개 Capability discovery를 MCP Tool로 노출한다.
Tool 이름은 Capability ID이며 입력 schema는 배포된 Runtime discovery 응답에서 받는다.
MCP 프로세스가 Registry 원본이나 DB를 직접 읽지 않는다.

## 코드 위치

구현은 `backend/src/teoria/integrations/runtime_http/`에 있다. `backend/src/teoria/entrypoints/mcp.py`는 실행 진입점, `tools.py`는 Tool 등록,
`schema.py`는 MCP 입력 schema 처리, `runtime_client.py`는 Runtime HTTP 호출,
`settings.py`는 환경변수를 소유한다. Capability별 실행 로직은 Platform에 둔다.

## 실행

저장소 루트에서 `TEORIA_ENV_FILE=deploy/compose/.env`를 지정하고 Runtime API URL과
token을 준비한다. 호스트에서 Compose Runtime에 접속하면 URL은
`http://localhost:8081/runtime-api`다. `http://runtime-api:8000`은 Compose 내부 주소다.
`TEORIA_MCP_RUNTIME_MODE=remote`만 지원한다.

MCP는 Runtime HTTP API를 호출하며 DB 권한과 Source 인증정보를 갖지 않는다.

```bash
uv run --project backend --locked --extra api teoria validate backend/registries
uv run --project backend --locked --extra mcp teoria-mcp
```

Codex 설정:

```toml
[mcp_servers.teoria]
command = "uv"
args = ["run", "--project", "backend", "--locked", "--extra", "mcp", "teoria-mcp"]
cwd = "/absolute/path/to/teoria"

[mcp_servers.teoria.env]
TEORIA_MCP_RUNTIME_MODE = "remote"
TEORIA_MCP_RUNTIME_API_URL = "http://localhost:8081/runtime-api"
TEORIA_MCP_RUNTIME_API_TOKEN = "development-token"
```

위 URL은 호스트에서 실행하는 예다. Compose 내부 MCP 컨테이너는
`http://runtime-api:8000`을 사용하고 token 예시는 실제 배포의 secret으로 교체한다.

운영 구조는 `AI Client → MCP Gateway → Runtime HTTP API`다. MCP는 Registry, Source 키와 DB 권한을 갖지 않는다.

Tool은 `exposure: public`인 Capability만 발견하며 제목과 설명에 active Artifact의
CapabilityVersion을 표시한다. Tool은 Ontology Object·Link와 provenance를 반환한다.
`_options.include_property_provenance`와 `_options.max_objects`로 응답 범위를 조절한다.

## 오류와 재시도

입력 schema는 Gateway 시작 시 Runtime discovery 응답에서 가져오며 MCP 코드에
Capability별 schema를 복제하지 않는다. 페이지 입력을 제공하는 Capability는 discovery
schema의 `page`, `page_size`를 그대로 사용하고, 응답의 `pagination.page`,
`pagination.page_size`, `pagination.total_items`, `pagination.total_pages`를 다음 호출
판단에 사용한다. Gateway는 결과를 임의로 합치거나 자동으로 다음 페이지를 호출하지 않는다.

Gateway 시작 시 수행하는 Capability discovery는 network error, timeout과 HTTP
`429`, `502`, `503`, `504`를 일시 장애로 분류하고 제한된 exponential backoff로
재시도한다. 최대 시도 횟수와 최초 backoff는
`TEORIA_MCP_RUNTIME_MAX_ATTEMPTS`, `TEORIA_MCP_RUNTIME_RETRY_BACKOFF_SECONDS`로
설정한다. `Retry-After`가 초 단위로 반환되면 그 값을 최소 대기시간으로 사용한다.
Discovery와 실행의 요청 timeout은 `TEORIA_MCP_RUNTIME_TIMEOUT_SECONDS`로 제한한다.

Capability 실행은 POST이며 향후 side effect Capability가 추가될 수 있으므로 Gateway가
자동 재시도하지 않는다. 오류는 Runtime의 `code`와 `message`를 보존하고 HTTP status,
시도 횟수와 재시도 가능 여부를 함께 분류한다. 호출자는 `retryable=true`만으로 재실행하지
말고 해당 Capability의 effect와 실행 결과 수신 여부를 확인해야 한다.

Docker 실행:

```bash
docker compose -f deploy/compose/compose.yaml --profile mcp run --rm mcp
```

## 검증

```bash
uv run --locked --project backend pytest backend/tests/integrations/runtime_http
```

MCP는 STDIO protocol을 사용하므로 애플리케이션 로그를 표준 출력에 추가하지 않는다.
환경변수의 기본값은 [환경 설정](../deployment/configuration.md), 실제 실행 계약은
[Platform Runtime](../platform/runtime.md)을 참고한다.
