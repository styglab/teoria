# Teoria MCP Gateway

`mcp/`는 Capability를 MCP Tool로 제공한다. 목표 운영 모드에서는 Runtime HTTP API만 호출하고 Source 키와 DB 권한을 갖지 않는다. 현재 STDIO 개발 모드는 embedded Platform Runtime을 사용한다.

```bash
uv run --locked --package teoria-mcp pytest mcp/tests
uv run --locked --package teoria-mcp teoria-mcp
```

`TEORIA_MCP_RUNTIME_MODE=remote`는 Runtime API client가 구현될 때까지 실행을 거부한다. 설정과 Codex 연결은 [MCP 문서](../docs/mcp.md)를 따른다.
