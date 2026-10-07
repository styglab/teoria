# Repository structure and ownership

경계는 코드 위치뿐 아니라 비밀정보, DB 권한과 배포 단위를 결정한다.

| 프로젝트 | 소유 | 제외 |
|---|---|---|
| `platform` | Business Ontology, Semantic Binding, Metadata Intelligence, Semantic Registry, Runtime, 직접 Source 실행, OpenMetadata REST integration | Prefect, MCP transport, OpenMetadata metadata 복제 |
| `pipelines` | Connector, Prefect, raw·정규화·적재, Data DB migration | Ontology, Capability, MCP |
| `mcp` | MCP Tool, protocol 변환, Runtime API client | Source 키, DB, Registry 실행 |
| `packages/provider_api` | API schema, request/response 검증, HTTP retry·오류 | Registry, Prefect, MCP |

## 통신과 의존

```text
pipelines ──SQL write contract──▶ Teoria Data DB
platform  ──SQL read contract───▶ Teoria Data DB
platform  ──REST reference──────▶ OpenMetadata
mcp       ──Runtime HTTP API────▶ platform
platform  ──▶ teoria-provider-api ◀── pipelines
```

- Pipeline 실행 코드는 Platform Runtime을 import하지 않는다.
- MCP는 Runtime API만 호출하며 Platform Runtime을 embedded import하지 않는다.
- `teoria-provider-api`는 Platform이나 Pipelines를 역으로 import하지 않는다.
- `common`, `shared`, `utils` 패키지는 만들지 않는다. 안정된 공통 계약만 이름 있는 패키지로 추출한다.
- 예외적으로 Pipeline 통합 검증 진입점은 Platform Registry를 지연 import할 수 있다.

`packages/`에는 둘 이상의 프로젝트가 실제로 사용하는 설치형 라이브러리만 둔다.
각 패키지는 독립 `pyproject.toml`, 테스트와 단일 책임을 가지며 Platform이나
Pipelines를 역으로 import하지 않는다. 미래 사용을 예상한 빈 패키지나
`common`, `shared`, `utils` 성격의 묶음은 만들지 않는다.

Platform 배포 이미지는 실행 경계에 따라 나눈다. `runtime` target은 Runtime 코드와
Registry만 포함하고, `authoring` target은 Admin·migration·검증에 필요한
`ontology_migrations/`, `references/`, `database/`를 추가로 포함한다.

## 계약 위치

| 목적 | 위치 |
|---|---|
| Runtime 직접 API·DB | `platform/registries/sources/` |
| 지속 수집 API | `pipelines/connectors/` |
| API→DB 정규화 | `pipelines/src/teoria_pipelines/normalization/` |
| Source·DB→Ontology 변환 | `platform/src/teoria/runtime/mapping/functions/` |
| Data DB schema | `pipelines/database/migrations/` |
| Teoria Application DB schema | `platform/database/migrations/` |
| OpenMetadata REST boundary | `platform/src/teoria/metadata/openmetadata/` |
| Business Ontology v2 | `platform/src/teoria/ontology/` |
| Semantic Binding | `platform/src/teoria/binding/` |
| Metadata Intelligence | `platform/src/teoria/intelligence/` |

OpenMetadata의 entity 본문은 Platform DB에 저장하지 않는다. Binding에
필요한 `MetadataTargetRef`만 `teoria_app`에 정규화해 저장하며 이는
metadata cache가 아니다. Capability는 독립 knowledge source로 유지하고
Ontology와의 연결은 Semantic Binding으로 표현한다.

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

배포 설정은 제품 이름이 아니라 실행 환경을 최상위 경계로 둔다.

```text
deploy/
├── compose/
│   ├── compose.yaml
│   ├── nginx/
│   └── openmetadata/   # Compose 전용 설정과 ingestion 예제
└── experimental/
    └── k3s/            # 아직 지원하지 않는 Kubernetes scaffold
```

Prefect와 OpenMetadata 서비스 정의는 모두 `compose.yaml`에 둔다. 특정
서비스의 Compose 전용 보조 파일만 `deploy/compose/<service>/`에 두며,
Kubernetes 배포가 지원 수준에 도달하기 전에는 모든 관련 scaffold를
`deploy/experimental/k3s/` 아래에 둔다.

```bash
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

새 기능은 의미·Runtime이면 `platform`, 지속 수집이면 `pipelines`, MCP protocol이면 `mcp`에 둔다.
특정 vertical domain의 정책은 해당 Domain Registry와 명시적인 기능 패키지에
두며, 두 번째 domain에서 재사용이 확인되기 전에는 Platform 공통 추상화로
승격하지 않는다.

## Naming

Teoria가 소유하는 repository path와 내부 ID의 기본 형식은 `snake_case`다.
예: `admin_ui/`, `runtime_client.py`, `get_company_profile.yaml`,
`001_create_runtime_tables.sql`. 예외는 도구 고정 이름, 외부 계약 원문,
`PascalCase`인 클래스·React 컴포넌트, `UPPER_SNAKE_CASE`인 환경변수와
`kebab-case`인 CLI·Docker·배포 리소스다. 기존 문서의 `kebab-case` 파일은
링크 호환을 위해 유지하며 신규 파일부터 이 규칙을 적용한다.
