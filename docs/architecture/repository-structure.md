# Repository structure and ownership

경계는 코드 위치뿐 아니라 비밀정보, DB 권한과 배포 단위를 결정한다.

| 프로젝트 | 소유 | 제외 |
|---|---|---|
| `platform` | Semantic Registry, 검증·발행, Runtime, 직접 Source 실행, DB 조회 | Prefect, MCP transport |
| `pipelines` | Connector, Prefect, raw·정규화·적재, Data DB migration | Ontology, Capability, MCP |
| `mcp` | MCP Tool, protocol 변환, Runtime API client | Source 키, DB, Registry 실행 |
| `packages/provider` | API schema, request/response 검증, HTTP retry·오류 | Registry, Prefect, MCP |

## 통신과 의존

```text
pipelines ──SQL write contract──▶ Teoria Data DB
platform  ──SQL read contract───▶ Teoria Data DB
mcp       ──Runtime HTTP API────▶ platform
platform  ──▶ teoria-provider ◀── pipelines
```

- Pipeline 실행 코드는 Platform Runtime을 import하지 않는다.
- MCP의 embedded import는 Runtime API 구현 전까지만 허용한다.
- `teoria-provider`는 Platform이나 Pipelines를 역으로 import하지 않는다.
- `common`, `shared`, `utils` 패키지는 만들지 않는다. 안정된 공통 계약만 이름 있는 패키지로 추출한다.
- 예외적으로 Pipeline 통합 검증 진입점은 Platform Registry를 지연 import할 수 있다.

## 계약 위치

| 목적 | 위치 |
|---|---|
| Runtime 직접 API·DB | `platform/registries/sources/` |
| 지속 수집 API | `pipelines/connectors/` |
| API→DB 정규화 | `pipelines/src/teoria_pipelines/normalization/` |
| Source·DB→Ontology 변환 | `platform/src/teoria/runtime/mapping/functions/` |
| Data DB schema | `pipelines/database/migrations/` |

같은 수집 API를 Source와 Connector에 중복 등록하지 않는다. Pipeline이 적재한 DB는 Platform의 Database Source와 Mapping으로 Ontology에 연결한다.

## Prefect 구조

```text
flows/           Task 조합과 파라미터
tasks/           재시도·관찰이 필요한 경계
connectors/      Provider API client
normalization/   순수 raw-to-table 변환
persistence/     raw·정규 데이터와 checkpoint 저장
checkpoints/     cursor와 재개 정책
```

- Flow는 얇게 유지한다.
- API 호출과 DB 쓰기는 Task로, 순수 변환은 일반 함수로 둔다.
- Deployment와 schedule은 `pipelines/prefect.yaml`에 둔다.
- Checkpoint는 모든 적재가 성공한 뒤 갱신한다.

## DB와 배포

- Pipeline 계정은 Data DB 쓰기, Runtime 계정은 정규 relation 읽기만 허용한다.
- MCP에는 Data DB 권한을 주지 않는다.
- migration과 Database Source 호환성은 통합 검증으로 확인한다.
- 각 배포 프로젝트는 자체 `pyproject.toml`과 Dockerfile을 갖고 루트 `uv.lock`을 공유한다.

```bash
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

새 기능은 의미·Runtime이면 `platform`, 지속 수집이면 `pipelines`, MCP protocol이면 `mcp`에 둔다.
