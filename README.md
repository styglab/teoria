# Teoria

Teoria는 의미 Registry와 Runtime, Prefect 기반 데이터 수집, MCP Gateway를 한 저장소에서 관리한다. 각 프로젝트는 독립 배포하며 Provider API 실행 계약만 `teoria-provider`로 공유한다.

```text
Data Pipelines ──write──▶ Teoria Data DB ◀──read── Semantic Platform
                                                    ▲
AI Client ──MCP──▶ MCP Gateway ──HTTP(target)───────┘
```

## 구성

| 경로 | 책임 |
|---|---|
| `platform/` | Source·Ontology·Mapping·Capability Registry와 Runtime |
| `pipelines/` | Connector, Prefect Flow, raw·정규 적재, DB migration |
| `mcp/` | Capability를 MCP Tool로 제공 |
| `packages/provider/` | 공통 API 요청·응답 계약과 HTTP 실행 |
| `deploy/` | 로컬 검증·실행용 Compose |
| `docs/` | 아키텍처와 작성·운영 규칙 |
| `archive/` | 시점별 검증 결과와 과거 산출물 |

상세 경계는 [Repository Structure](docs/architecture/repository-structure.md)를 따른다.

## 시작

```bash
cp .env.example .env
uv sync --locked --all-packages --all-groups
```

테스트와 계약 검증:

```bash
uv run --locked --package teoria-provider pytest packages/provider/tests
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-mcp pytest mcp/tests

uv run --locked --package teoria-platform teoria validate platform/registries
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

MCP STDIO:

```bash
uv run --locked --package teoria-mcp teoria-mcp
```

Prefect와 Data DB:

```bash
docker compose --env-file .env \
  -f deploy/compose/ingestion.yaml \
  up --build -d
```

Prefect UI는 `http://localhost:4200`에서 확인한다.

## 문서

- [문서 안내](docs/README.md)
- [Architecture](docs/architecture/overview.md)
- [Source 작성](docs/registry/source-authoring.md)
- [Ontology](docs/registry/ontology_registry.md)
- [Pipeline과 Prefect](docs/ingestion/prefect.md)
- [Validation](docs/registry/validation.md)
- [MCP](docs/mcp.md)
