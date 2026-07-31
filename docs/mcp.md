# Teoria MCP Gateway

`mcp/`는 Registry Capability를 MCP Tool로 노출한다. Tool 이름은 Capability ID이며 입력 schema는 Registry에서 생성한다.

## 실행

현재 STDIO 개발 모드는 embedded Runtime을 사용한다.

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
TEORIA_MCP_RUNTIME_MODE = "embedded"
TEORIA_MCP_EMBEDDED_REGISTRY_PATH = "/absolute/path/to/teoria/platform/registries"
```

목표 운영 구조는 `AI Client → MCP Gateway → Runtime HTTP API`다. Remote 전환 후 MCP는 Source 키, DB 권한, Registry Loader와 Capability Runner를 갖지 않는다. 현재 `remote` mode는 Runtime API client가 구현될 때까지 실행을 거부한다.

Tool은 Ontology Object·Link와 provenance를 반환한다. `_options.include_property_provenance`와 `_options.max_objects`로 응답 범위를 조절한다.

Docker 실행:

```bash
docker compose -f deploy/compose.yaml --profile mcp run --rm mcp
```
