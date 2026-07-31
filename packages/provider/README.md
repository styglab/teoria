# Teoria Provider

`teoria-provider`는 Platform Source와 Pipeline Connector가 공유하는 작은 Python 라이브러리다. 서비스가 아니므로 포트, 데이터베이스, 독립 Docker 배포를 갖지 않는다.

포함 범위:

- Provider API wire contract schema
- 입력 검증과 HTTP request 생성
- HTTP 실행, credential interface, retry와 구조화 오류
- 응답 record path와 wire type 검증

포함하지 않는 범위:

- Semantic Registry, Ontology, Mapping, Capability
- Pipeline Definition, Prefect Flow, 정규화와 DB 적재
- MCP 또는 Runtime HTTP client

```bash
uv run --locked --package teoria-provider pytest packages/provider/tests
```
