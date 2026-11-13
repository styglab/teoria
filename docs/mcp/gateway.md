# Teoria MCP Gateway

Tool 목록은 연결한 Runtime의 게시 artifact와 공개 Capability 설정에 따른다.
업무 Capability가 없는 Runtime의 빈 Tool 목록은 정상이며 기존 조달 Tool을 다시 노출하지 않는다. Gateway는 시작할 때 discovery를 고정하므로
Runtime bundle 변경 뒤 MCP 프로세스와 클라이언트 연결을 재시작한다.

MCP는 Runtime API의 공개 Capability discovery를 MCP Tool로 노출한다.
Tool 이름은 Capability ID이며 입력 schema는 배포된 Runtime discovery 응답에서 받는다.
MCP 프로세스가 Registry 원본이나 DB를 직접 읽지 않는다.

## 코드 위치

MCP protocol은 `backend/src/teoria/entrypoints/mcp/`에 둔다. `server.py`는 STDIO 실행,
`tools.py`는 Tool 변환, `schemas.py`는 MCP schema, `settings.py`는 환경 설정을 소유한다.
Runtime HTTP 호출과 오류는 `backend/src/teoria/integrations/runtime_http/runtime_client.py`가 담당한다.
MCP protocol 패키지는 Runtime HTTP client를 사용하며 DB·기능 구현을 import하지 않는다.

## 실행

Kubernetes에 배포한 Runtime의 접근 가능한 HTTPS 주소와 전용 token을 준비한다.
MCP는 클라이언트 호스트에서 실행하며 Kubernetes 내부 DNS나 Docker 네트워크에 의존하지 않는다.
`TEORIA_MCP_RUNTIME_MODE=remote`만 지원하며 DB 권한과 Source 인증정보를 갖지 않는다.

```bash
export TEORIA_MCP_RUNTIME_MODE=remote
export TEORIA_MCP_RUNTIME_API_URL=https://teoria.example.com/runtime-api
# token은 프로세스 환경 또는 접근을 제한한 TEORIA_ENV_FILE로 공급한다.
uv run --project backend --locked --extra mcp teoria-mcp
```

`TEORIA_MCP_RUNTIME_API_TOKEN`도 실행 전에 설정해야 한다. token을 저장소 설정에 기록하지 않는다.
사설 인증서를 쓰는 환경은 MCP 호스트의 신뢰 저장소를 구성한다.

저장소의 `.codex/config.toml`은 같은 `teoria-mcp` 명령을 직접 실행하며 기본 비활성화 상태다.
실제 checkout에 맞게 `cwd`를 설정하고 URL·token을 공급한 뒤 활성화한다.

```toml
[mcp_servers.teoria]
command = "uv"
args = ["run", "--project", "backend", "--locked", "--extra", "mcp", "teoria-mcp"]
cwd = "/absolute/path/to/teoria"
```

운영 구조는 `AI Client → 로컬 MCP STDIO 프로세스 → Runtime HTTP API`다.
별도 MCP 컨테이너·Compose bridge·상시 MCP 서버 배포를 요구하지 않는다.

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

MCP는 클라이언트 연결마다 STDIO 프로세스를 실행한다. Runtime bundle 변경 뒤
MCP 프로세스와 클라이언트 연결을 재시작해 discovery를 갱신한다.

## 검증

```bash
uv run --locked --project backend --all-extras pytest backend/tests/entrypoints/mcp backend/tests/integrations/runtime_http
uv run --locked --project backend --extra mcp python .agents/skills/test-teoria-mcp/scripts/smoke_test.py --discovery-only
```

discovery-only 검증은 초기화·Tool 조회를 확인한다. 반환 Tool 목록은 연결한 Runtime의
공개 Capability 설정과 비교하며, 과거 조달 Tool을 검증 목적으로 재활성화하지 않는다.

MCP는 STDIO protocol을 사용하므로 애플리케이션 로그를 표준 출력에 추가하지 않는다.
환경변수의 기본값은 [환경 설정](../deployment/configuration.md), 실제 실행 계약은
[Platform Runtime](../platform/runtime.md)을 참고한다.
