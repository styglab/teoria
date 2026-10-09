# Teoria MCP Gateway

`mcp/`는 Registry Capability를 MCP Tool로 노출한다. Tool 이름은 Capability ID이며 입력 schema는 Registry에서 생성한다.

## 실행

MCP는 Runtime HTTP API를 호출하며 DB 권한과 Source 인증정보를 갖지 않는다.

```bash
uv run --locked --package teoria-platform teoria validate platform/registries
uv run --locked --package teoria-mcp teoria-mcp
```

Codex 설정:

```toml
[mcp_servers.teoria]
command = "uv"
args = ["run", "--locked", "--package", "teoria-mcp", "teoria-mcp"]
cwd = "/absolute/path/to/teoria"

[mcp_servers.teoria.env]
TEORIA_MCP_RUNTIME_MODE = "remote"
TEORIA_MCP_RUNTIME_API_URL = "http://runtime-api:8000"
TEORIA_MCP_RUNTIME_API_TOKEN = "development-token"
```

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
