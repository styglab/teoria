# Teoria MCP Gateway

`mcp/`는 Capability를 MCP Tool로 제공하고 Runtime HTTP API만 호출한다. Source 키와 DB 권한은 Platform Runtime에만 둔다.

```bash
uv run --locked --package teoria-mcp pytest mcp/tests
uv run --locked --package teoria-mcp teoria-mcp
```

`TEORIA_MCP_RUNTIME_MODE=remote`만 지원한다. 설정과 Codex 연결은 [MCP 문서](../docs/mcp.md)를 따른다.
