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

Tool은 Ontology Object·Link와 provenance를 반환한다. `_options.include_property_provenance`와 `_options.max_objects`로 응답 범위를 조절한다.

Docker 실행:

```bash
docker compose -f deploy/compose.yaml --profile mcp run --rm mcp
```
