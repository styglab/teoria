# Teoria platform guide

Teoria는 OpenMetadata가 관리하는 데이터 자산과 Teoria의 Business Ontology 및
Capability를 연결해 검증 가능한 business context를 제공한다. 전체 권위 경계는
[Architecture](architecture/overview.md)를 따른다.

## 저장소

| 경로 | 책임 |
|---|---|
| `platform/` | Ontology, Binding, Intelligence, Runtime, 직접 Source 실행 |
| `pipelines/` | Connector, Prefect, raw·정규 적재, Data DB migration |
| `mcp/` | MCP protocol과 Runtime HTTP client |
| `packages/provider_api/` | Provider wire 계약과 HTTP 실행 |
| `deploy/` | 지원되는 Compose와 실험 단계의 k3s 스캐폴드 |

## 로컬 실행

```bash
cp deploy/compose/.env.example deploy/compose/.env
export TEORIA_ENV_FILE=deploy/compose/.env
uv sync --locked --all-packages --all-groups
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml up --build -d
```

기본 진입점은 다음과 같다.

| 대상 | 주소/명령 |
|---|---|
| Admin UI | `http://localhost:8081/` |
| Admin API | `http://localhost:8081/admin-api/docs` |
| Runtime API | `http://localhost:8081/runtime-api/docs` |
| Prefect | `http://localhost:8081/prefect/` |
| MCP | `uv run --locked --package teoria-mcp teoria-mcp` |

OpenMetadata는 `metadata` profile로 선택 실행한다. 상세한 환경변수는
[Configuration](configuration.md), 서비스 운영은 [Deployment](../deploy/README.md)를
참고한다.

## 주요 작업 흐름

### 데이터 운영자

Connector와 Prefect Flow를 관리하고 raw·정규 적재가 모두 성공한 뒤 checkpoint가
이동하는지 확인한다. [Prefect guide](ingestion/prefect.md)를 따른다.

### Metadata 관리자

OpenMetadata에서 asset, schema, glossary, owner와 lineage를 관리한다. Teoria에는
OpenMetadata entity 본문을 복제하지 않는다.

### Ontology owner와 Binding reviewer

Published version에서 새 Draft를 만들고 review·approval 후 publish한다. Binding과
AI Suggestion은 승인 전까지 권위 정보가 아니다. 상세 계약은
[Ontology](architecture/ontology.md)를 따른다.

### Capability 개발자

Runtime Object, Mapping과 Capability를 Domain Registry에 정의한다. 직접 실행 API는
Source, 지속 수집 API는 Connector로 작성한다. [Registry guide](registry/README.md)와
[Source authoring](registry/source-authoring.md)을 따른다.

### API/MCP 사용자

배포된 Runtime의 `/v1/capabilities`에서 사용할 수 있는 Capability와 입력 schema를
조회하고 `/v1/capabilities/{id}:execute`를 호출한다. MCP는 같은 Runtime API의
protocol adapter다.

## 검증

```bash
uv run --locked --package teoria-provider-api pytest packages/provider_api/tests
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-mcp pytest mcp/tests
uv run --locked --package teoria-platform teoria validate platform/registries
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
docker compose -f deploy/compose/compose.yaml config --quiet
```
