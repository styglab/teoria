# Teoria platform guide

이 문서는 Teoria가 어떻게 구성되고, 각 사용자가 어떤 경로로 사용하는지
설명하는 시작점이다.

## Teoria란 무엇인가

Teoria는 Data Catalog의 대체품이 아니다. OpenMetadata가 설명하는 데이터와
Teoria의 Business Ontology·Capability를 연결하고, AI가 사용할 수 있는
검증된 business context를 만드는 플랫폼이다.

```text
External API / DB / File
          │
          ▼
       Prefect ─────────────── 수집·변환·동기화
          │
          ▼
   PostgreSQL / Data Store ─── 실제 데이터
          │
          ▼
     OpenMetadata ──────────── Technical/Semantic Metadata
          │
          ├──────────────┐
          ▼              ▼
 Business Ontology ◀─ Semantic Binding ─▶ Capabilities
          └──────────────┬───────────────┘
                         ▼
                  Context Engine (next)
                         ▼
                    API / MCP / Agent
```

## 누가 무엇을 소유하는가

| 시스템 | 소유 | 소유하지 않음 |
|---|---|---|
| Prefect/Pipelines | workflow, connector, raw/core 적재, backfill, checkpoint | metadata 의미, ontology |
| Data DB | 실제 수집·정규화 데이터 | metadata governance |
| OpenMetadata | asset, schema, column, glossary, tag, owner, lineage, quality | Business Ontology |
| Teoria App DB | Ontology, Binding, Suggestion, Review, audit, context 설정 | OpenMetadata entity 본문 |
| Runtime | Source/Mapping/Capability 실행 | pipeline orchestration |
| MCP | protocol 변환과 Runtime client | DB·Source credential |

로컬 Compose의 PostgreSQL은 Data Plane과 Control/Application Plane 두
인스턴스로 나뉜다. `postgres`는 대량 수집·Backfill·Runtime query가 발생하는
`teoria_data`만 소유한다. `platform-postgres`는 서로 독립된
`teoria_app`, `prefect`, `openmetadata_db` database를 DB별 role로 운영한다.
같은 인스턴스라는 이유로 database 간 SQL join이나 metadata 복제를 허용하지 않는다.

## 저장소 구성

| 경로 | 설명 |
|---|---|
| `platform/` | Ontology, Binding, Intelligence, Runtime, Admin API/UI |
| `pipelines/` | Prefect, Connector, normalization, Data DB migration |
| `mcp/` | MCP gateway와 Runtime HTTP client |
| `packages/provider/` | Provider wire contract와 HTTP 실행 |
| `deploy/compose/` | 로컬/단일 서버 Compose |
| `deploy/compose/openmetadata/` | Compose용 OpenMetadata ingestion 설정 |
| `docs/` | Architecture, authoring, operations, roadmap |

## 로컬 실행

```bash
cp deploy/compose/.env.example deploy/compose/.env
export TEORIA_ENV_FILE=deploy/compose/.env

docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml \
  --profile metadata up --build -d
```

기본 접근점:

| 화면/API | URL |
|---|---|
| Teoria Admin UI | `http://localhost:8081/` |
| Admin API docs | `http://localhost:8081/admin-api/docs` |
| Runtime API docs | `http://localhost:8081/runtime-api/docs` |
| Prefect UI | `http://localhost:8081/prefect/` |
| OpenMetadata UI/API | `http://localhost:8585/` |

OpenMetadata는 optional overlay지만 Metadata/Binding 기능을 사용할 환경에서는
함께 실행해야 한다.

## Runtime Registry와 Business Ontology

기존 YAML Ontology는 현재 Capability가 실행할 입출력 Runtime Contract다.
지속 가능한 업무 의미인 Business Ontology v2와 동일한 것이 아니며, 관리
화면에서도 `Runtime Registry`로 구분한다.

- 44개 Runtime 객체는 모두 migration manifest에 분류되어 있다.
- 23개 Business Concept은 `company` 0.1.0과 `procurement` 0.4.0에 게시됐다.
- 12개 집계/조회 projection은 Capability contract로 유지한다.
- 9개 평가·근거 객체는 assessment result model로 유지한다.

Capability target은 Capability 자체, 선언된 input, 선언된 output 중 하나다.
Teoria는 현재 immutable Registry release에서 target을 검증한 뒤 Stable
Concept과 연결한다. 의미가 정확히 같지 않은 필드는 편의상 추론해 연결하지
않는다.

## 첫 Binding Intelligence 흐름

1. Metadata에서 OpenMetadata Table을 선택한다.
2. Column의 `Binding 후보 생성`을 실행한다.
3. Suggestions에서 추천 Stable Concept, confidence, 대안 후보와 evidence를 확인한다.
4. Suggestion을 승인하면 Teoria가 OpenMetadata 원천 버전을 다시 확인한다.
5. 원천이 바뀌지 않았을 때만 `draft` Binding을 생성한다.
6. Bindings에서 별도의 reviewer가 Draft를 승인하거나 거절한다.

Suggestion 승인과 Binding 승인을 분리했기 때문에 AI 추천이 곧바로 권위 있는
Semantic Binding이 되지 않는다. 원천 version이 변경되면 승인을 차단하고
후보를 다시 계산해야 한다.

Ontology Authoring 화면은 Published 버전 직접 편집을 허용하지 않는다.
새 버전은 Create Draft로 생성하고 `Draft → Review → Approved → Published`
순서로 전환한다.

## 주요 사용 흐름

### 1. 데이터 운영자

1. `pipelines/connectors/`에 수집 API 계약을 작성한다.
2. Prefect Flow로 incremental/backfill을 실행한다.
3. raw와 canonical 적재가 모두 성공한 뒤 checkpoint가 갱신되는지 확인한다.
4. Prefect가 일회성 OpenMetadata ingestion Job을 실행해 PostgreSQL asset을 갱신한다.
5. 실행·재시도는 Prefect UI에서, 적재된 metadata는 OpenMetadata에서 확인한다.

### 2. Metadata 관리자

1. Admin UI의 **Metadata**에서 OpenMetadata 연결과 asset을 확인한다.
2. Description/Glossary/Tag는 OpenMetadata를 권위 저장소로 관리한다.
3. Teoria DB에 OpenMetadata entity 본문을 복제하지 않는다.
4. Intelligence Suggestion은 **Suggestions**에서 검토한다.

### 3. Ontology Owner

1. Published version에서 새 Draft를 만든다.
2. Object, Property, Relationship을 편집한다.
3. validation, semantic diff, Binding impact를 확인한다.
4. Review와 Approval을 거쳐 publish한다.
5. 생성된 Runtime Artifact checksum과 audit history를 확인한다.

Published version은 API뿐 아니라 PostgreSQL trigger로도 수정이 차단된다.

### 4. Binding Reviewer

1. Admin UI의 **Bindings**로 이동한다.
2. Stable Ontology Concept과 OpenMetadata Glossary/Data Asset target을 확인한다.
3. 새 연결은 Draft로 생성한다.
4. evidence와 authority를 검토해 approve 또는 reject한다.
5. 더 이상 유효하지 않은 Approved Binding은 deprecate한다.

같은 Stable Concept과 Target의 활성 Binding은 Ontology version이 바뀌어도
중복 생성할 수 없다.

### 5. Capability 개발자

1. Runtime 직접 API/DB를 Source Registry로 작성한다.
2. Runtime Mapping과 Semantic Binding을 구분한다.
3. Capability input/output contract와 효과를 명시한다.
4. Registry validation과 실제 verification을 실행한다.
5. 향후 CapabilityTargetRef를 Stable Concept에 연결한다.

### 6. AI/Agent 사용자 — 향후 흐름

Agent는 OpenMetadata 전체 JSON이나 Ontology 전체를 직접 읽지 않는다.
Context Engine에 business term 또는 intent를 전달하고, Teoria가 승인된
Ontology·Binding·Capability와 metadata quality를 조합한 Context Package를
반환한다.

## Governance 규칙

- AI 결과는 Suggestion이지 authoritative metadata가 아니다.
- Description/Glossary/Tag의 최종 저장소는 OpenMetadata다.
- Ontology와 Binding의 최종 저장소는 Teoria App DB다.
- Runtime Mapping은 데이터 변환이며 Semantic Binding이 아니다.
- 승인 actor는 request body가 아닌 인증 principal이다.
- evidence 대상의 version이 변경되면 승인 전에 재평가한다.
- 중·고위험 변경은 자동 적용하지 않는다.

## 기존 Runtime Registry와 Business Ontology v2

Admin UI의 `Runtime Registry`는 현재 Capability 실행에 사용되는 YAML
Ontology와 Mapping을 보여준다. `Bindings`와 Ontology Authoring API는
PostgreSQL 기반 Business Ontology v2를 사용한다. 전환 상태와 Object별
분류는 [Legacy Registry Migration](architecture/legacy-registry-migration.md)을
따른다.

## 검증 명령

```bash
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-platform teoria validate platform/registries

uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines

uv run --locked --package teoria-mcp pytest mcp/tests

cd platform/admin-ui
npm test -- --run
npm run build
```

DB migration 또는 Compose 변경 시:

```bash
docker compose -f deploy/compose/compose.yaml config --quiet
```

## 더 읽을 문서

- [Target Architecture](architecture/ai-native-metadata-platform.md)
- [Repository Ownership](architecture/repository-structure.md)
- [Semantic Governance](architecture/semantic-governance.md)
- [Ontology Authoring](architecture/ontology-authoring.md)
- [OpenMetadata Integration](../deploy/compose/openmetadata/README.md)
- [Product Roadmap](roadmap.md)
